"""LAN service for the surface-velocity reconstruction model.

Serves the panel plus a small JSON API.  Standard library only - the training
environment already carries torch/scipy/numpy and adding a web framework to it
would be one more version to keep in step for no gain at this size.

    python web/server.py                     # http://0.0.0.0:8760
    python web/server.py --port 9000 --device cuda
    python web/server.py --rebuild-index     # after fetching new data

Point a browser at any address it prints; the page is plain HTML/CSS/JS with no
build step and no external requests, so it works for anyone on the same LAN.
"""
from __future__ import annotations

import argparse
import json
import math
import mimetypes
import socket
import socketserver
import sys
import threading
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from web.index import DEFAULT_DATA_ROOT, DEFAULT_INDEX_PATH, SectionStore, load_index  # noqa: E402
from web.infer import ArmRegistry  # noqa: E402
from web.payload import build_payload  # noqa: E402
from rebuild_vel.client import PermanentAPIError  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"

MAX_LIMIT = 500
DEFAULT_MEASUREMENT_LIMIT = 200
#: a posted section is arrays of numbers; anything past this is abuse, and
#: reading it fully before refusing would be the cost the cap exists to stop
MAX_BODY_BYTES = 16 * 1024 * 1024


def platform_time(text: str, *, end: bool = False) -> str:
    """Widen a caller's date or time to the platform's ``yyyy-MM-dd HH:mm:ss.SSS``.

    ``/flow/originalDataFilterPage`` deserialises its bounds straight into
    ``java.sql.Timestamp``, which rejects anything without milliseconds - a
    plain ``2026-08-31 00:00:00`` comes back as a 500.  Callers here type the
    same strings the picker shows, so the widening belongs on this side.

    A bare date means the whole day, so the upper bound widens to its last
    millisecond rather than to midnight - a zero-width window would quietly
    answer "one measurement" for a day that has fifty.
    """
    text = text.strip().replace("/", "-").replace("T", " ")
    date, _, clock = text.partition(" ")
    if not clock:
        return f"{date} {'23:59:59.999' if end else '00:00:00.000'}"
    parts = clock.split(":")
    if len(parts) == 1:
        return f"{date} {parts[0]}:" + ("59:59.999" if end else "00:00.000")
    if len(parts) == 2:
        return f"{date} {parts[0]}:{parts[1]}:" + ("59.999" if end else "00.000")
    seconds = parts[2]
    if "." not in seconds:
        seconds += ".999" if end else ".000"
    elif len(seconds.split(".")[1]) < 3:
        seconds = seconds.split(".")[0] + "." + seconds.split(".")[1].ljust(3, "0")
    parts[2] = seconds
    return f"{date} " + ":".join(parts[:3])


class ServiceError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


#: Why a live timestamp could not be drawn, in the panel's own words.  The
#: reason codes and the messages behind them are the pipeline's vocabulary -
#: they name internal tables, tolerances and thresholds - and they belong in
#: the run log, not in front of a reviewer who only needs to know whether this
#: measurement can be reconstructed at all.  So each refusal is stated as the
#: outcome it is: no raw observations, no water level, nothing to draw.
SECTION_REFUSAL: dict[str, str] = {
    "no_raw_input": "无法获得原始观测测速数据",
    "no_algorithm_lines": "该测次没有算法测得的测速线",
    "too_few_lines": "该测次的测速线太少",
    "mostly_zero": "该测次的标定流速几乎全为零",
    "dominant_value": "该测次的标定流速几乎全为同一个值",
    "velocity_out_of_range": "该测次的标定流速超出可用范围",
    "bad_velocity": "该测次的标定流速缺失或异常",
    "bad_depth": "该测次的测速线没有水深",
    "bad_water_level": "该测次没有水位记录",
    "duplicate_x": "该测次的测速线起点距不唯一",
    "missing_identity": "该测次缺少站点、设备或时间",
    "nonfinite": "该测次含有非数值的字段",
}

#: Why a caller's section was refused, keyed by the reason codes the cleaning
#: pipeline raises.  These are for whoever drives the model programmatically -
#: the codes are the stable contract, the messages are what to show a human
#: alongside them.
SECTION_REFUSAL_API: dict[str, str] = {
    "no_raw_input": "no raw velocity observations in any of the three raw tables",
    "too_few_lines": "fewer lines than the configured minimum",
    "missing_identity": "station, device and time are required",
    "bad_water_level": "water level is missing or non-finite",
    "duplicate_x": "line positions are not strictly increasing",
    "bad_depth": "line depth missing and bed elevation unavailable",
    "bad_velocity": "line surface velocity has non-finite values",
    "velocity_out_of_range": "max surface velocity exceeds the configured ceiling",
    "mostly_zero": "target velocities are almost all zero",
    "dominant_value": "one exact velocity value dominates the section",
    "no_algorithm_lines": "no algorithm-given lines in the section",
    "nonfinite": "a value in the input is not numeric",
}


class SectionRefused(ValueError):
    """The caller's section did not pass the gate; ``reason`` is a stable code."""

    def __init__(self, reason: str) -> None:
        super().__init__(SECTION_REFUSAL_API.get(reason, reason))
        self.reason = reason


def _clean_caller_section(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate one caller-supplied section and convert it to numpy arrays.

    The pipeline's ``clean_measurement`` speaks the platform workbook's shape
    (``lines``, ``raw_stiv`` / ``raw_of`` / ``raw_of_traj`` tables).  Callers
    here hold one section's arrays, not a workbook, so this adapter maps the
    public shape onto the internal one - the three raw tables collapse into the
    one source the pipeline would have picked anyway - and runs the very same
    gate.  ``QualityOptions.for_inference`` is the right severity: this is
    showing a measurement, not training on it, so only structurally necessary
    checks fire and nothing is thrown away for being a bad training example.
    """
    from rebuild_vel.quality import QualityOptions, SectionQualityError, clean_measurement

    if not isinstance(raw, dict):
        raise SectionRefused("missing_identity")
    try:
        # the same looseness as live parsing: integer-looking numerics arrive
        # as strings through some producers, and `_finite` accepts them
        lines_raw = raw.get("lines") or []
        lines: list[dict[str, Any]] = []
        for item in lines_raw:
            if not isinstance(item, dict):
                raise SectionRefused("nonfinite")
            lines.append({
                "x": item.get("x"),
                "depth": item.get("depth"),
                "bed_elevation": item.get("bed_elevation"),
                "v_surface": item.get("v_surface"),
                "confidence": item.get("confidence"),
                "angle": item.get("angle"),
                "is_algo": bool(item.get("is_algo", True)),
                "line_num": item.get("line_num", 0),
            })
        raw_rows = [
            {"x": row.get("x"), "raw_v": row.get("v"),
             "confidence": row.get("confidence"), "angle": row.get("angle"),
             "t_start": row.get("t_start"), "t_end": row.get("t_end"),
             "video_segment_id": row.get("segment_id") if row.get("segment_id") is not None else idx}
            for idx, row in enumerate(raw.get("observations") or [])
            if isinstance(row, dict)
        ]
        measurement: dict[str, Any] = {
            "station": raw.get("station") or "external",
            "station_name": raw.get("station_name") or "",
            "device": raw.get("device") or "external",
            "time": raw.get("time") or "external",
            "water_level": raw.get("water_level"),
            "water_width": raw.get("water_width"),
            "section_area": raw.get("section_area"),
            "surface_avg_velocity": raw.get("surface_avg_velocity"),
            "max_depth": raw.get("max_depth"),
            "aver_depth": raw.get("aver_depth"),
            "version": raw.get("version") or "external",
            "lines": lines,
            "raw_stiv": raw_rows,
        }
        return clean_measurement(measurement, QualityOptions.for_inference())
    except SectionQualityError as exc:
        raise SectionRefused(exc.reason) from exc


class Service:
    """Request-independent state: the index, the shard cache, the models."""

    def __init__(self, *, data_root: str, index_path: str, rebuild_index: bool,
                 device: str, arms_file: Optional[str], log: Callable[[str], None]) -> None:
        self.log = log
        self.index = load_index(index_path, data_root, rebuild=rebuild_index, log=log)
        self.store = SectionStore(self.index)
        self.registry = (ArmRegistry.from_file(arms_file, device)
                         if arms_file else ArmRegistry(device=device))
        self.device = device
        # one inference at a time: several browser tabs hitting the model at
        # once would only thrash the same weights
        self._infer_lock = threading.Lock()
        self._client_lock = threading.Lock()
        self._client: Any = None
        # the last answer to "what is newest today", keyed by date and kept for
        # a couple of minutes - a roomful of readers refreshing the panel would
        # otherwise each set off a dozen platform questions to hear the same one
        self._latest: dict[str, tuple[float, dict[str, Any]]] = {}

    # -- platform API ------------------------------------------------------
    def _flow_client(self) -> Any:
        """Lazily build the read-only platform client (needs accounts.json)."""
        with self._client_lock:
            if self._client is None:
                from rebuild_vel.accounts import AccountPool
                from rebuild_vel.client import FlowClient

                self._client = FlowClient(AccountPool(None), timeout=120.0)
            return self._client

    def live_measurements(self, station: str, device: str, begin: str, end: str) -> list[dict[str, Any]]:
        try:
            client = self._flow_client()
        except Exception as exc:  # noqa: BLE001
            raise ServiceError(
                HTTPStatus.SERVICE_UNAVAILABLE,
                f"平台凭据不可用（accounts.json）：{exc}") from exc
        rows: list[dict[str, Any]] = []
        try:
            for _page, measurement in client.iter_measurements(
                    station, device, begin, end, page_size=200, measure_result=1):
                when = str(measurement.get("measureTime") or "")
                if when:
                    rows.append({"device": device, "time": when[:19]})
        except Exception as exc:  # noqa: BLE001
            raise ServiceError(HTTPStatus.BAD_GATEWAY, f"平台查询失败：{exc}") from exc
        rows.sort(key=lambda r: r["time"], reverse=True)
        return rows

    #: How many devices ``live_latest`` asks about, how many answers it hands
    #: back, and how long it keeps them.  One device costs a single list call,
    #: measured in the low hundreds of milliseconds, so a dozen is a couple of
    #: seconds - small enough to spend on every page load, and wide enough that
    #: the newest timestamp of the day is almost always in hand.  The panel
    #: walks the candidates in order and opens the first that reconstructs, so
    #: a handful is the right width: five covers the case where the newest
    #: timestamps are all on devices whose export is currently failing.
    LIVE_LATEST_DEVICES = 12
    LIVE_LATEST_WANT = 5
    LIVE_LATEST_TTL = 120.0

    def live_latest(self, date: str) -> dict[str, Any]:
        """The newest live device-days on ``date``, newest first.

        The panel opens on a live reconstruction, so on arrival it has to know
        which one to open.  Nothing can simply be asked: the platform's list
        endpoint is per device, and the panel's own corpus ends three weeks
        before the panel went up, so it can describe history and nothing else.

        What the corpus can still say is which devices were reporting most
        recently, and that is the only ranking available for free.  Over this
        index the answer is emphatic - forty-nine devices stop on the same
        afternoon - so the ranking is a flat tie broken deterministically and
        the probe set is, in practice, "the devices that were live last", which
        is the right dozen to ask about today.

        Each device is then asked once for the day's timestamps, and the newest
        from each becomes a candidate.  A device the platform refuses to answer
        for is not allowed to sink the whole day: its message is kept only so
        that a day on which *every* device failed can say why.
        """
        key = f"{date}|{self.LIVE_LATEST_WANT}"
        now = time.monotonic()
        hit = self._latest.get(key)
        if hit and now - hit[0] < self.LIVE_LATEST_TTL:
            return hit[1]

        ranked: list[tuple[str, str, str, str]] = []
        for station in self.store.stations():
            for device in station["devices"]:
                rows = device.get("measurements") or []
                ranked.append((max((row[0] for row in rows), default=""),
                               station["code"], station.get("name") or "", device["device"]))
        ranked.sort(reverse=True)

        begin, end = platform_time(date), platform_time(date, end=True)
        candidates: list[dict[str, Any]] = []
        probed, failure = 0, ""
        for _, code, name, device in ranked[: self.LIVE_LATEST_DEVICES]:
            probed += 1
            try:
                rows = self.live_measurements(code, device, begin, end)
            except ServiceError as exc:
                failure = exc.message
                continue
            if rows:
                candidates.append({
                    "station": code,
                    "name": name,
                    "device": device,
                    "time": rows[0]["time"],
                    "n": len(rows),
                })
        candidates.sort(key=lambda c: c["time"], reverse=True)
        out = {
            "date": date,
            "probed": probed,
            "candidates": candidates[: self.LIVE_LATEST_WANT],
            "reason": "" if candidates else failure,
        }
        self._latest[key] = (now, out)
        self.log(f"  live/latest {date}: {probed} device(s) asked, "
                 f"{len(candidates)} with data")
        return out

    def live_section(self, station: str, device: str, when: str) -> dict[str, Any]:
        from rebuild_vel.parse import parse_merged_export
        from rebuild_vel.quality import QualityOptions, SectionQualityError, clean_measurement

        try:
            client = self._flow_client()
        except Exception as exc:  # noqa: BLE001
            raise ServiceError(
                HTTPStatus.SERVICE_UNAVAILABLE,
                f"平台凭据不可用（accounts.json）：{exc}") from exc
        try:
            payload = client.get_bytes("/flow/procedureDataMergeExport", {
                "stationCode": station,
                "deviceCode": device,
                "measureTimeList": [when],
            })
        except PermanentAPIError as exc:
            # 平台确认这个测次没有过程数据文件——不是通道故障，是数据本身
            # 不存在（测次太新或设备未上传），按找不到资源处理。
            if "没有过程数据文件" in str(exc):
                raise ServiceError(
                    HTTPStatus.NOT_FOUND,
                    f"该测次在平台上没有过程数据文件（{when}）") from exc
            raise ServiceError(HTTPStatus.BAD_GATEWAY, f"平台导出失败：{exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ServiceError(HTTPStatus.BAD_GATEWAY, f"平台导出失败：{exc}") from exc
        if not payload:
            raise ServiceError(HTTPStatus.NOT_FOUND, "该测次在平台上没有导出文件（procedureData）")
        parsed = parse_merged_export(payload)
        if not parsed.measurements:
            detail = "；".join(parsed.errors) or "工作簿里没有可解析的测次"
            raise ServiceError(HTTPStatus.NOT_FOUND, f"平台返回的表格无法解析：{detail}")
        measurement = parsed.measurements[0]
        measurement["station"] = station
        if not measurement.get("station_name"):
            for entry in self.index["stations"]:
                if entry["code"] == station:
                    measurement["station_name"] = entry["name"]
                    break
        try:
            # for_inference, not the default: the default options are corpus
            # filters for training data, and they reject most of a real
            # device-day.  A reviewer looking at a live timestamp wants to see
            # what the model does with that measurement, so only the checks
            # needed to build a drawable section are applied.
            return clean_measurement(measurement, QualityOptions.for_inference())
        except SectionQualityError as exc:
            raise ServiceError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "这个测次无法成图："
                + SECTION_REFUSAL.get(exc.reason, "该测次的数据不满足成图条件")) from exc

    # -- inference ---------------------------------------------------------
    def predict(self, section: dict[str, Any], wanted: Optional[list[str]]) -> dict[str, Any]:
        with self._infer_lock:
            return self.registry.predict_all(section, len(section["x"]), wanted)

    def reconstruct(self, raw: dict[str, Any], wanted: Optional[list[str]]) -> dict[str, Any]:
        """Run the arms on a caller-supplied section.

        Cleaning happens under the same lock as inference: both walk numpy
        arrays derived from caller/platform input, and one reader at a time
        keeps a malformed payload from racing a legitimate one through the
        shared stack.  Refusals carry a stable machine-readable code.
        """
        with self._infer_lock:
            try:
                section = _clean_caller_section(raw)
            except SectionRefused:
                raise
            except Exception as exc:  # noqa: BLE001 - never leak a stack trace
                raise SectionRefused("nonfinite") from exc
            return build_payload(section, self.registry.predict_all(section, len(section["x"]), wanted),
                                 source="external")


# ---------------------------------------------------------------------------
# routing
# ---------------------------------------------------------------------------
def _jsonable(value: Any) -> Any:
    """Make a payload safe for ``json.dumps`` -> ``JSON.parse``.

    Python writes non-finite floats as bare ``NaN`` / ``Infinity``, which is not
    JSON and which the browser's ``JSON.parse`` rejects outright - so a single
    undefined statistic would take the whole panel down with a parse error
    instead of drawing the section.  Payload builders already convert these to
    None; this is the backstop for the ones that slip through, and it turns a
    dead panel into a null the frontend already knows how to render as "—".
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _limit(params: dict[str, list[str]], default: int) -> int:
    try:
        value = int(params.get("limit", [default])[0])
    except ValueError:
        return default
    return max(1, min(value, MAX_LIMIT))


def _required(params: dict[str, list[str]], name: str) -> str:
    value = (params.get(name) or [""])[0].strip()
    if not value:
        raise ServiceError(HTTPStatus.BAD_REQUEST, f"缺少参数 {name}")
    return value


def handle_api(service: Service, path: str, params: dict[str, list[str]]) -> Any:
    if path == "/api/meta":
        return {
            "device": service.device,
            "data_root": service.index.get("data_root"),
            "index_built_at": service.index.get("built_at"),
            "n_stations": service.index.get("n_stations"),
            "n_sections": service.index.get("n_sections"),
            "arms": service.registry.info(),
        }

    if path == "/api/stations":
        query = (params.get("q") or [""])[0].strip().lower()
        limit = _limit(params, MAX_LIMIT)
        rows = []
        for entry in service.store.stations():
            haystack = f"{entry['code']} {entry['name']}".lower()
            if query and query not in haystack:
                continue
            rows.append({
                "code": entry["code"],
                "name": entry["name"],
                "n": entry["n"],
                "devices": [{"device": d["device"], "n": d["n"]} for d in entry["devices"]],
            })
            if len(rows) >= limit:
                break
        return {"total": service.index.get("n_stations"), "returned": len(rows), "stations": rows}

    if path == "/api/measurements":
        station = _required(params, "station")
        device = (params.get("device") or [""])[0].strip() or None
        rows = service.store.measurements(station, device)
        if not rows:
            raise ServiceError(HTTPStatus.NOT_FOUND, f"站点 {station} 没有已入库的测次")
        limit = _limit(params, DEFAULT_MEASUREMENT_LIMIT)
        return {"station": station, "total": len(rows), "measurements": rows[:limit]}

    if path == "/api/section":
        station = _required(params, "station")
        device = _required(params, "device")
        when = _required(params, "time")
        arms = [a for a in (params.get("arms") or [""])[0].split(",") if a] or None
        source = (params.get("source") or ["cache"])[0]
        if source == "live":
            section = service.live_section(station, device, when)
            origin = "live"
        else:
            try:
                section = service.store.get(station, device, when)
            except KeyError as exc:
                raise ServiceError(HTTPStatus.NOT_FOUND, str(exc)) from exc
            origin = "cache"
        predictions = service.predict(section, arms)
        return build_payload(section, predictions, source=origin)

    if path == "/api/live/measurements":
        station = _required(params, "station")
        device = _required(params, "device")
        begin = _required(params, "begin")
        end = _required(params, "end")
        rows = service.live_measurements(
            station, device,
            platform_time(begin), platform_time(end, end=True),
        )
        return {"station": station, "device": device, "total": len(rows), "measurements": rows}

    if path == "/api/live/latest":
        # the date comes from the panel, which is the clock the reader is
        # looking at; the server's own date is only the fallback
        date = (params.get("date") or [""])[0].strip() or time.strftime("%Y-%m-%d")
        return service.live_latest(date)

    if path == "/api/reconstruct":
        raise ServiceError(HTTPStatus.METHOD_NOT_ALLOWED,
                           "POST 一个 JSON 断面到 /api/reconstruct；接口文档见 /api_docs.html")


    if path == "/api/health":
        return {"ok": True}

    raise ServiceError(HTTPStatus.NOT_FOUND, f"no such endpoint: {path}")


def make_handler(service: Service) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "RebuildVel/1.0"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            service.log("  %s - %s" % (self.address_string(), fmt % args))

        # -- helpers -------------------------------------------------------
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            # the panel is meant to be reloaded after a re-fetch, not cached
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _send_json(self, status: int, payload: Any) -> None:
            body = json.dumps(_jsonable(payload), ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _fail(self, status: int, message: str) -> None:
            self._send_json(status, {"error": message, "status": int(status)})

        def _static(self, path: str) -> None:
            relative = unquote(path).lstrip("/") or "index.html"
            target = (STATIC_DIR / relative).resolve()
            try:
                target.relative_to(STATIC_DIR.resolve())
            except ValueError:
                return self._fail(HTTPStatus.FORBIDDEN, "path escapes the static root")
            if target.is_dir():
                target = target / "index.html"
            if not target.is_file():
                return self._fail(HTTPStatus.NOT_FOUND, f"not found: {relative}")
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type in (
                    "application/javascript", "application/json"):
                content_type += "; charset=utf-8"
            self._send(HTTPStatus.OK, target.read_bytes(), content_type)

        # -- verbs ---------------------------------------------------------
        def _read_body(self) -> Any:
            """Parse one JSON body with sane limits; ``ServiceError`` on failure."""
            try:
                length = min(int(self.headers.get("Content-Length") or 0),
                             MAX_BODY_BYTES)
            except ValueError:
                length = 0
            raw = self.rfile.read(length) if length else b""
            if not raw:
                raise ServiceError(HTTPStatus.BAD_REQUEST, "请求体为空，需要一个 JSON 断面")
            try:
                return json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ServiceError(HTTPStatus.BAD_REQUEST,
                                   f"请求体不是合法的 JSON：{exc}") from exc

        def _dispatch(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            params = parse_qs(parsed.query)
            if path.startswith("/api/"):
                self._send_json(HTTPStatus.OK, handle_api(service, path, params))
            else:
                self._static(parsed.path)

        def do_GET(self) -> None:  # noqa: N802
            try:
                self._dispatch()
            except ServiceError as exc:
                self._fail(exc.status, exc.message)
            except Exception as exc:  # noqa: BLE001 - the panel must survive anything
                service.log(traceback.format_exc())
                self._fail(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

        do_HEAD = do_GET

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            params = parse_qs(parsed.query)
            try:
                if path != "/api/reconstruct":
                    raise ServiceError(HTTPStatus.NOT_FOUND, f"no such endpoint: {path}")
                body = self._read_body()
                arms = [a for a in (params.get("arms") or [""])[0].split(",") if a] or None
                self._send_json(HTTPStatus.OK, service.reconstruct(body, arms))
            except SectionRefused as exc:
                self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {
                    "error": str(exc), "reason": exc.reason, "code": "section_refused"})
            except ServiceError as exc:
                self._fail(exc.status, exc.message)
            except Exception as exc:  # noqa: BLE001
                service.log(traceback.format_exc())
                self._fail(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

    return Handler


def _lan_addresses(port: int) -> list[str]:
    addresses = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in addresses:
                addresses.append(ip)
    except OSError:
        pass
    return [f"http://{ip}:{port}" for ip in addresses] or [f"http://127.0.0.1:{port}"]


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LAN panel for the reconstruction model")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8760)
    parser.add_argument("--data", default=DEFAULT_DATA_ROOT)
    parser.add_argument("--index", default=DEFAULT_INDEX_PATH)
    parser.add_argument("--rebuild-index", action="store_true")
    parser.add_argument("--arms", default=None, help="JSON file overriding the arm registry")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    # the banner carries Chinese arm labels and Windows consoles are not UTF-8,
    # so a redirected log would otherwise be mojibake
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = parse_args(argv)
    log = lambda message: print(message, flush=True)  # noqa: E731
    log("building service state ...")
    service = Service(
        data_root=args.data, index_path=args.index, rebuild_index=args.rebuild_index,
        device=args.device, arms_file=args.arms, log=log,
    )
    for arm in service.registry.info():
        mark = "ok     " if arm["available"] else "MISSING"
        log(f"  arm {arm['id']:<5} {mark} {arm['label']:<12} {arm['checkpoint']}"
            + ("" if arm["available"] else f"  ({arm['reason']})"))
    log(f"  {service.index['n_stations']} stations / "
        f"{service.index['n_sections']:,} measurements  ({service.index['data_root']})")

    handler = make_handler(service)
    socketserver.TCPServer.allow_reuse_address = True
    try:
        httpd = ThreadingHTTPServer((args.host, args.port), handler)
    except OSError as exc:
        log(f"cannot bind {args.host}:{args.port} - {exc}")
        return 1
    httpd.daemon_threads = True
    log("")
    log(f"  local    http://127.0.0.1:{args.port}")
    for url in _lan_addresses(args.port):
        log(f"  network  {url}")
    log("")
    log("Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("\nstopping")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

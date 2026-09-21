# 时序库数据获取API

# 如何获取认证token

## 调用登录接口

请求地址：[https://aiflow2.dashuiyun.cn:9999/prod-api/loginNoVerify](https://aiflow2.dashuiyun.cn:9999/prod-api/loginNoVerify)

参数示例:

```json
{
  "password": "<你的密码>",
  "username": "admin"
}
```

返回示例：

```json
{
    "msg": "操作成功",
    "code": 200,
    "token": "eyJhbGciOiJIUzUxMiJ9.eyJsb2dpbl91c2VyX2tleSI6ImUyMTJjYTA4LTUxY2QtNDM2NS05MDdjLTBmM2E3MWY5NmQ5ZCJ9.VLaIDXiKGWe8QBbp2NumN92dyuhUdxIpyVoIvfr0eGnkCwZoPXv-TRZQK275DQdioszxQqzoEHBuZplXf1n8zg"
}
```

## token使用方式

放入http请求头中：

![image.png](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/r4mlQ5oDX8yNglxo/img/362a61f7-c4de-44e0-bab2-de798a1d45e2.png)

![image.png](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/r4mlQ5oDX8yNglxo/img/5c8360e2-7c02-4901-a262-17d38111358f.png)

# 1.时序库表清单：

![Pasted Graphic 4.png](https://alidocs.oss-cn-zhangjiakou.aliyuncs.com/res/r4mlQ5oDX8yNglxo/img/0b1c0cb9-1807-41b7-aac5-36194cb3429f.png)

# 2.表描述

2.1：蒸发站原始数据（对应表序号1）

2.2：流场仪原始数据（对应表序号2）

2.3：流量原始数据（对应表序号3）

2.4：原始流量测速线（对应表序号4）

2.5：水位原始数据（对应表序号5）

2.6：第三方水位原始数据（比测）（对应表序号6）

2.7：测流设备原始数据示范案例（对应表序号7）

2.8：图像水位原始数据示范案例（对应表序号8）

2.9：站点流量（对应表序号9）

2.10：站点流量测速线（对应表序号10）

2.11：站点水位（对应表序号11）

# 3.接口地址

## 响应状态

| 状态码 | 说明 | schema |
| --- | --- | --- |
| 200 | OK | ResultModel«List«OriginalDataFlowStiv对象»» |
| 201 | Created |  |
| 401 | Unauthorized |  |
| 403 | Forbidden |  |
| 404 | Not Found |  |

## 3.1：蒸发站原始数据（对应表序号1）

请求地址: https://aiflow2.dashuiyun.cn/prod-api/client/monitorEvaporate/page

参数示例:

```json
{
    "count": 20,
    "page": 1,
    "request": {
        "beginTime": "2025-05-12 00:00:00",
        "endTime": "2025-05-19 23:59:59",
        "stationCode": "00265",
        "responseType": 1
    }
}
```

描述：

| 参数名称 | 参数说明 | 请求类型 | 是否必须 | 数据类型 | schema |
| --- | --- | --- | --- | --- | --- |
| 请求参数体«历史蒸发查询参数» | 请求参数体 | body | true | 请求参数体«历史蒸发查询参数» | 请求参数体«历史蒸发查询参数» |
| count | 每页条数，默认为10,示例值(10) |  | false | integer(int32) |  |
| page | 页数，第几页，默认为1,示例值(1) |  | false | integer(int32) |  |
| request | 自定义入参 |  | false | 历史蒸发查询参数 | 历史蒸发查询参数 |
| beginTime | 开始时间 |  | true | TimestampReq | TimestampReq |
| deviceCode |  |  | false | string |  |
| endTime | 结束时间 |  | true | TimestampReq | TimestampReq |
| responseType |  |  | false | integer |  |
| stationCode | 水文站站码 |  | true | string |  |

返回示例：

```json
{
	"code": 0,
	"data": [
		{
			"addWater": 0,
			"dataSources": 0,
			"dateEvaporateNum": 0,
			"dateRainNum": 0,
			"dayEvaporateNum": 0,
			"dayRainNum": 0,
			"deviceCode": "",
			"drawWater": 0,
			"drawWaterDepth": 0,
			"label": "",
			"measureTime": {
				"date": 0,
				"day": 0,
				"hours": 0,
				"minutes": 0,
				"month": 0,
				"nanos": 0,
				"seconds": 0,
				"time": 0,
				"timezoneOffset": 0,
				"year": 0
			},
			"overflowWater": 0,
			"overflowWaterDepth": 0,
			"remarks": "",
			"stationCode": "",
			"uploadStatus": 0,
			"waterLevelAfter": 0,
			"waterLevelBefore": 0
		}
	],
	"msg": "",
	"pageInfo": {
		"current": 0,
		"pages": 0,
		"size": 0,
		"total": 0
	}
}
```

描述：

| 参数名称 | 参数说明 | 类型 | schema |
| --- | --- | --- | --- |
| code |  | integer(int32) | integer(int32) |
| data |  | array | 实时蒸发数据对象 |
| addWater | 加水量(单位：ml) | number(double) |  |
| dataSources | 数据来源: 0-设备计算，1-系统插补，2-设备插补 | integer(int32) |  |
| dateEvaporateNum | 时段蒸发量(单位：mm) | number(double) |  |
| dateRainNum | 时段降雨量(单位：mm) | number(double) |  |
| dayEvaporateNum | 日蒸发量(单位：mm) | number(double) |  |
| dayRainNum | 日降雨量(单位：mm) | number(double) |  |
| deviceCode | 设备码 | string |  |
| drawWater | 汲水量：从仪器中吸取水的总量(单位：ml) | number(double) |  |
| drawWaterDepth | 汲水量折合水深：从仪器中吸取水的总量，折合成水的深度汲水量折合水深：从仪器中吸取水的总量，折合成水的深度(单位：mm) | number(double) |  |
| label | 标签 | string |  |
| measureTime | 时间 | TimestampRes | TimestampRes |
| overflowWater | 溢水量：从仪器中溢出水的总量(单位：ml) | number(double) |  |
| overflowWaterDepth | 溢水量折合水深：从仪器中溢出水的总量，折合成水的深度(单位：mm) | number(double) |  |
| remarks | 备注 | string |  |
| stationCode | 水文站站码 | string |  |
| uploadStatus | 上报状态，0未上报，1为已上报 | integer(int32) |  |
| waterLevelAfter | 加(汲)水后水面高度：仪器中增加（吸取）水之后的水面高度(单位：mm) | number(double) |  |
| waterLevelBefore | 加(汲)水前水面高度：仪器中增加（吸取）水之前的水面高度(单位：mm) | number(double) |  |
| msg |  | string |  |
| pageInfo |  | 分页信息 | 分页信息 |
| current | 当前页码号 | integer(int64) |  |
| pages | 共有多少页 | integer(int64) |  |
| size | 每页条数 | integer(int64) |  |
| total | 总条数 | integer(int64) |  |

## 3.2：流场仪原始数据（对应表序号2）

请求地址: https://aiflow2.dashuiyun.cn/prod-api/client/monitorField/page

参数示例:

```json
{
    "count": 10,
    "page": 1,
    "request": {
        "days": 7,
        "stationCode": "00095"
    }
}
```

描述：

| 参数名称 | 参数说明 | 请求类型 | 是否必须 | 数据类型 | schema |
| --- | --- | --- | --- | --- | --- |
| 请求参数体«MonitorFlowQueryDto» | 请求参数体 | body | true | 请求参数体«MonitorFlowQueryDto» | 请求参数体«MonitorFlowQueryDto» |
| count | 每页条数，默认为10,示例值(10) |  | false | integer(int32) |  |
| page | 页数，第几页，默认为1,示例值(1) |  | false | integer(int32) |  |
| request | 自定义入参 |  | false | MonitorFlowQueryDto | MonitorFlowQueryDto |
| days | 近几天数据 |  | true | integer |  |
| measureResult | 测量结果(缺省时默认为1):0-失败,1-成功,2-全部 |  | false | integer |  |
| stationCode | 水文站站码 |  | true | string |  |

返回示例：

```json
{
	"code": 0,
	"data": [
		{
			"algorithmResult": 0,
			"deviceCode": "",
			"failureDetail": "",
			"failureType": 0,
			"flowFieldDiagram": "",
			"measureResult": 0,
			"measureTime": {
				"date": 0,
				"day": 0,
				"hours": 0,
				"minutes": 0,
				"month": 0,
				"nanos": 0,
				"seconds": 0,
				"time": 0,
				"timezoneOffset": 0,
				"year": 0
			},
			"stationCode": "",
			"version": "",
			"waterDeviceCode": "",
			"waterLevel": 0
		}
	],
	"msg": "",
	"pageInfo": {
		"current": 0,
		"pages": 0,
		"size": 0,
		"total": 0
	}
}
```

描述：

| 参数名称 | 参数说明 | 类型 | schema |
| --- | --- | --- | --- |
| code |  | integer(int32) | integer(int32) |
| data |  | array | OriginalDataFlowField |
| algorithmResult | 算法返回结果值 | number(double) |  |
| deviceCode | 设备码 | string |  |
| failureDetail | 失败详情 | string |  |
| failureType | 失败类型: 0-摄像头异常;1-水位数据异常;2-算法异常 | integer(int32) |  |
| flowFieldDiagram | 流场图 | string |  |
| measureResult | 测量结果，0-失败，1-成功 | integer(int32) |  |
| measureTime | 时间 | Timestamp | Timestamp |
| stationCode | 水文站站码 | string |  |
| version | 设备程序版本 | string |  |
| waterDeviceCode | 水位来源设备(设备码) | string |  |
| waterLevel | 水位(m) | number(double) |  |
| msg |  | string |  |
| pageInfo |  | 分页信息 | 分页信息 |
| current | 当前页码号 | integer(int64) |  |
| pages | 共有多少页 | integer(int64) |  |
| size | 每页条数 | integer(int64) |  |
| total | 总条数 | integer(int64) |  |

## 3.3：流量原始数据（对应表序号3）

请求地址: https://aiflow2.dashuiyun.cn:9999/prod-api/flow/originalDataFilterPage

参数示例:

```json
{
    "count": 10, // 每页展示多少条
    "page": 1, // 展示第几页
    "request": {
        "beginTime": "2025-05-12 15:49:24.850", // 开始时间
        "deviceCode": "FD000422003588", // 逻辑设备码
        "endTime": "2025-05-19 15:49:24.850", // 结束时间
        "stationCode": "04170" // 站码
        "waterLevelType": null,
        "uploadStatus": null,
        "dataType": null,
        "reliability": null,
        "nightMark": null,
        "label": ""
    }
}
```

描述：

| 参数名称 | 参数说明 | 请求类型 | 是否必须 | 数据类型 | schema |
| --- | --- | --- | --- | --- | --- |
| 请求参数体«DataQueryDto» | 请求参数体 | body | true | 请求参数体«DataQueryDto» | 请求参数体«DataQueryDto» |
| count | 每页条数，默认为10,示例值(10) |  | false | integer(int32) |  |
| page | 页数，第几页，默认为1,示例值(1) |  | false | integer(int32) |  |
| request | 自定义入参 |  | false | DataQueryDto | DataQueryDto |
| beginTime | 开始时间：yyyy-MM-dd HH:mm:ss.SSS |  | true | string |  |
| dataType | 数据类型：-1-率定工具得出;0-实时计算;1-加测;2-补测; |  | false | integer |  |
| deviceCode | 设备码 |  | true | string |  |
| endTime | 结束时间：yyyy-MM-dd HH:mm:ss.SSS |  | true | string |  |
| label | 标签 |  | false | string |  |
| measureResult | 测量结果(缺省时默认为1):0-失败,1-成功,2-全部 |  | false | integer |  |
| nightMark | 昼夜标志：0-白天;1-晚上 |  | false | integer |  |
| reliability | 可靠性：1-可靠;2-不可靠 |  | false | integer |  |
| stationCode | 站码 |  | true | string |  |
| uploadStatus | 上报状态，0未上报，1为已上报 |  | false | integer |  |
| waterLevelType | 水位数据类型：0-比测水位，1-图像水位 |  | false | integer |  |

返回示例：

```json
{
    "code": 200,
    "msg": "操作成功",
    "data": [
        {
            "stationName": null,
            "measureTime": "2025-05-16 10:15:00.000",
            "waterLevel": 456.989990234375,
            "levelModel": 1,
            "waterLevelType": 2,
            "waterDeviceCode": "FD000236527834",
            "sectionArea": 62.29,
            "waterWidth": 69.58999633789062,
            "surfaceAverageVelocity": null,
            "virtualFlow": null,
            "conversionVelocity": null,
            "conversionFlow": null,
            "fittingVelocity": 0.742,
            "fittingFlow": 46.24525613896549,
            "waterVelocity": 0.73,
            "waterFlow": 45.50012689994481,
            "predictFlow": null,
            "predictVelocity": null,
            "originalValueProp": null,
            "maxDepth": null,
            "averDepth": null,
            "maxSurfaceVelocity": null,
            "outCrossMeasTime": null,
            "uploadStatus": 1,
            "uploadDataSource": 3,
            "forecastMethod": 1,
            "dataSource": null,
            "dataType": 1,
            "reliability": null,
            "nightMark": 0,
            "videoLength": null,
            "videoUrl": null,
            "videoUrlSecond": null,
            "videoUrlThird": null,
            "videoUrls": [],
            "procedureDataFile": "MinioFile_02:/profile/upload/deviceResultData/procedureData/00620/FD000236527834/2025/05/16/20250516_101500/20250516101500.xlsx",
            "version": "V4.6.5.windows_v2.2.19_2024/12/19",
            "label": null,
            "remarks": null,
            "transportType": 0,
            "stationCode": "00620",
            "deviceCode": "FD000236527834",
            "dateTime": null,
            "dataCount": null,
            "limit1": null,
            "limit2": null,
            "beginTime": null,
            "endTime": null,
            "measureTimeList": null,
            "fittingVerify": false,
            "errorRange": null
        }
    ],
    "pageInfo": {
        "current": 1,
        "pages": 1,
        "size": 32,
        "total": 32
    }
}
```

描述：

**响应参数**

| 参数名称 | 参数说明 | 类型 | schema |
| --- | --- | --- | --- |
| code |  | integer(int32) | integer(int32) |
| data |  | array | OriginalDataFlowStiv对象 |
| averDepth | 平均水深 | number(double) |  |
| beginTime |  | Timestamp | Timestamp |
| date |  | integer |  |
| day |  | integer |  |
| hours |  | integer |  |
| minutes |  | integer |  |
| month |  | integer |  |
| nanos |  | integer |  |
| seconds |  | integer |  |
| time |  | integer |  |
| timezoneOffset |  | integer |  |
| year |  | integer |  |
| conversionFlow | 换算流量(m3/s) | number(double) |  |
| conversionVelocity | 换算流速 (m/s) | number(double) |  |
| dataCount | 按日期统计数 | integer(int32) |  |
| dataSource | 本条数据来源，0为正常计算得出，1为率定工具得出 | integer(int32) |  |
| dataType | 数据类型：-1-率定工具;0-正常流程;1-加测;2-补测;3-重测 | integer(int32) |  |
| dateTime | 日期时间 | string |  |
| deviceCode | 设备码 | string |  |
| endTime |  | Timestamp | Timestamp |
| date |  | integer |  |
| day |  | integer |  |
| hours |  | integer |  |
| minutes |  | integer |  |
| month |  | integer |  |
| nanos |  | integer |  |
| seconds |  | integer |  |
| time |  | integer |  |
| timezoneOffset |  | integer |  |
| year |  | integer |  |
| errorRange | 误差范围（m） | number(double) |  |
| fittingFlow | 拟合流量(m3/s) | number(double) |  |
| fittingVelocity | 拟合流速(m/s) | number(double) |  |
| fittingVerify |  | boolean |  |
| forecastMethod | 预测方法 | integer(int32) |  |
| label | 标签 | string |  |
| levelModel | 水位模式 0：本机水位，1：系统水位 | integer(int32) |  |
| limit1 |  | integer(int64) |  |
| limit2 |  | integer(int64) |  |
| maxDepth | 最大水深 | number(double) |  |
| maxSurfaceVelocity | 最大表面流速 | number(double) |  |
| measureTime | 时间 | Timestamp | Timestamp |
| date |  | integer |  |
| day |  | integer |  |
| hours |  | integer |  |
| minutes |  | integer |  |
| month |  | integer |  |
| nanos |  | integer |  |
| seconds |  | integer |  |
| time |  | integer |  |
| timezoneOffset |  | integer |  |
| year |  | integer |  |
| measureTimeList |  | array | string |
| nightMark | 昼夜标志：0-白天;1-晚上 | integer(int32) |  |
| originalValueProp | 流速原始真值占比 | number(double) |  |
| outCrossMeasTime | 借测断面时间 | Timestamp | Timestamp |
| date |  | integer |  |
| day |  | integer |  |
| hours |  | integer |  |
| minutes |  | integer |  |
| month |  | integer |  |
| nanos |  | integer |  |
| seconds |  | integer |  |
| time |  | integer |  |
| timezoneOffset |  | integer |  |
| year |  | integer |  |
| predictFlow | 预测流量(m3/s) | number(double) |  |
| predictVelocity | 预测流速(m/s) | number(double) |  |
| procedureDataFile | 过程数据文件 | string |  |
| reliability | 可靠性：1-可靠;2-不可靠,.... | integer(int32) |  |
| remarks | 备注 | string |  |
| sectionArea | 断面面积 | number(double) |  |
| stationCode | 水文站站码 | string |  |
| stationName | 站点名称 | string |  |
| surfaceAverageVelocity | 表面平均流速(m/s) | number(double) |  |
| transportType | 数据来源类型：0-系统接口;10-北斗(磐钴)转发; | integer(int32) |  |
| uploadDataSource | 上报数据来源 0-拟合值,1-换算值,2-原始值,3-预测值 | integer(int32) |  |
| uploadStatus | 上报状态，0未上报，1为已上报 | integer(int32) |  |
| version | 设备程序版本 | string |  |
| videoLength | 视频时长(s) | integer(int64) |  |
| videoUrl | 视频地址 | string |  |
| videoUrlSecond | 2号视频地址 | string |  |
| videoUrlThird | 3号视频地址 | string |  |
| videoUrls | 视频地址 | array | CameraVideoFile |
| cameraIndex | 摄像头序号 | integer |  |
| videoIndex | 视频序号 | integer |  |
| videoUrl | 视频地址 | string |  |
| virtualFlow | 虚流量(m3/s) | number(double) |  |
| waterDeviceCode | 水位来源设备 | string |  |
| waterFlow | 流量(m3/s) | number(double) |  |
| waterLevel | 水位(m) | number(double) |  |
| waterLevelType | 水位数据类型：0-比测水位，1-图像水位 | integer(int32) |  |
| waterVelocity | 流速(m/s) | number(double) |  |
| waterWidth | 水宽(河宽)(m) | number(double) |  |
| msg |  | string |  |
| pageInfo |  | 分页信息 | 分页信息 |
| current | 当前页码号 | integer(int64) |  |
| pages | 共有多少页 | integer(int64) |  |
| size | 每页条数 | integer(int64) |  |
| total | 总条数 | integer(int64) |  |

## 3.4：原始流量测速线（对应表序号4）

请求地址: https://aiflow2.dashuiyun.cn:9999/prod-api/flow/vDistribution

参数示例:

```json
{
  "deviceCode":"FD000236527834", // 逻辑设备码
  "stationCode":"00620", // 站码
  "measureTime":"2025-05-16 10:00:00.000" // 测速时间
}
```

返回示例：

```json
{
	"code": 200,
	"data": {
		"deviceVideoInfoVo": {
			"videoHeight": 0,
			"videoWith": 0
		},
		"flowStivSpeedLineVos": [
			{
				"lineNum": 0,
				"srcEndPixX": 0,
				"srcEndPixY": 0,
				"srcStartPixX": 0,
				"srcStartPixY": 0,
				"startPointDistance": 0,
				"vlineDataSource": 0,
				"vlineExpressArea": 0,
				"vlineExpressFlow": 0,
				"vlineSurfaceVelocity": 0
			}
		],
		"measureTime": "",
		"sectionPointVos": [
			{
				"elevation": 0,
				"startDistance": 0
			}
		],
		"surfaceAverageVelocity": 0,
		"virtualFlow": 0,
		"waterLevel": 0
	},
	"msg": "操作成功",
	"pageInfo": {
		"current": 0,
		"pages": 0,
		"size": 0,
		"total": 0
	}
}
```

描述：

**响应参数**

| 参数名称 | 参数说明 | 类型 | schema |
| --- | --- | --- | --- |
| code |  | integer(int32) | integer(int32) |
| data |  | VelocityDistributionVo | VelocityDistributionVo |
| deviceVideoInfoVo | 设备视频信息 | DeviceVideoInfoVo | DeviceVideoInfoVo |
| videoHeight | 视频高 | integer |  |
| videoWith | 视频宽 | integer |  |
| flowStivSpeedLineVos | 测速线数据 | array | OriginalDataFlowStivSpeedLineVo |
| lineNum | 测速线编号 | integer |  |
| srcEndPixX | 原图终点像素X坐标 | number |  |
| srcEndPixY | 原图终点像素Y坐标 | number |  |
| srcStartPixX | 原图起点像素X坐标 | number |  |
| srcStartPixY | 原图起点像素Y坐标 | number |  |
| startPointDistance | 河岸起点距(m) | number |  |
| vlineDataSource | 测速线数据来源，0代表插值，1代表算法给出 | integer |  |
| vlineExpressArea | 部分面积(m2) | number |  |
| vlineExpressFlow | 部分流量(m3/s) | number |  |
| vlineSurfaceVelocity | 测速线表面流速(m/s) | number |  |
| measureTime | 时间 | string |  |
| sectionPointVos | 断面图信息 | array | SectionPointVo |
| elevation | 水位高程 | number |  |
| startDistance | 左岸起点距 | number |  |
| surfaceAverageVelocity | 水面平均流速(m/s)、虚流速 | number(double) |  |
| virtualFlow | 虚流量(m3/s) | number(double) |  |
| waterLevel | 水位(m) | number(double) |  |
| msg |  | string |  |
| pageInfo |  | 分页信息 | 分页信息 |
| current | 当前页码号 | integer(int64) |  |
| pages | 共有多少页 | integer(int64) |  |
| size | 每页条数 | integer(int64) |  |
| total | 总条数 | integer(int64) |  |

## 3.5：水位原始数据（对应表序号5）

请求地址: https://aiflow2.dashuiyun.cn:9999/prod-api/level/originalDataFilterPage

参数示例:

```json
{
    "count": 10,
    "page": 1,
    "request": {
        "beginTime": "2025-05-12 00:00:00.361",
        "deviceCode": "WD010656017040",
        "endTime": "2025-05-19 23:59:59.361",
        "stationCode": "00601",
        "uploadStatus": null,
        "label": "",
        "eliminate": null
    }
}
```

描述：

| 参数名称 | 参数说明 | 请求类型 | 是否必须 | 数据类型 | schema |
| --- | --- | --- | --- | --- | --- |
| 请求参数体«LevelDataQueryDto» | 请求参数体 | body | true | 请求参数体«LevelDataQueryDto» | 请求参数体«LevelDataQueryDto» |
| count | 每页条数，默认为10,示例值(10) |  | false | integer(int32) |  |
| page | 页数，第几页，默认为1,示例值(1) |  | false | integer(int32) |  |
| request | 自定义入参 |  | false | LevelDataQueryDto | LevelDataQueryDto |
| beginTime | 开始时间：yyyy-MM-dd HH:mm:ss.SSS |  | true | string |  |
| deviceCode | 设备码 |  | true | string |  |
| eliminate | 异常标识：0-正常水位，1-异常水位 |  | false | integer |  |
| endTime | 结束时间：yyyy-MM-dd HH:mm:ss.SSS |  | true | string |  |
| label | 标签 |  | false | string |  |
| stationCode | 站码 |  | true | string |  |
| uploadStatus | 上报状态，0未上报，1为已上报 |  | false | integer |  |

返回示例：

```json
{
	"code": 0,
	"data": [
		{
			"amendTag": 0,
			"beginTime": {
				"date": 0,
				"day": 0,
				"hours": 0,
				"minutes": 0,
				"month": 0,
				"nanos": 0,
				"seconds": 0,
				"time": 0,
				"timezoneOffset": 0,
				"year": 0
			},
			"comMeasureWaterLevel": 0,
			"dataSources": 0,
			"deviceCode": "",
			"eliminate": 0,
			"endTime": {
				"date": 0,
				"day": 0,
				"hours": 0,
				"minutes": 0,
				"month": 0,
				"nanos": 0,
				"seconds": 0,
				"time": 0,
				"timezoneOffset": 0,
				"year": 0
			},
			"imageWaterLevel": 0,
			"label": "",
			"limit1": 0,
			"limit2": 0,
			"measureTime": {
				"date": 0,
				"day": 0,
				"hours": 0,
				"minutes": 0,
				"month": 0,
				"nanos": 0,
				"seconds": 0,
				"time": 0,
				"timezoneOffset": 0,
				"year": 0
			},
			"measureTimeList": [],
			"nsbdConfig": {
				"bottomWaterLevelHeight": 0,
				"bottomWaterLevelPointy": 0,
				"dynamicWaterLevel": 0,
				"dynamicWaterLevelPointy": 0,
				"topWaterLevelHeight": 0,
				"topWaterLevelPointy": 0,
				"virtualGaugePoints": {
					"p1Gauge": 0,
					"p2Gauge": 0,
					"p3Gauge": 0,
					"p4Gauge": 0
				},
				"zeroPointHeight": 0
			},
			"originalTag": 0,
			"originalWaterLevel": 0,
			"pictureUrl": "",
			"pointNum": 0,
			"rawDataUrl": "",
			"remarks": "",
			"reportLevel": 0,
			"stationCode": "",
			"stationName": "",
			"uploadStatus": 0,
			"version": ""
		}
	],
	"msg": "",
	"pageInfo": {
		"current": 0,
		"pages": 0,
		"size": 0,
		"total": 0
	}
}
```

描述：

| 参数名称 | 参数说明 | 类型 | schema |
| --- | --- | --- | --- |
| code |  | integer(int32) | integer(int32) |
| data |  | array | OriginalDataLevelAi对象 |
| amendTag | 修正标签: 0-正常，1-异常 | integer(int32) |  |
| beginTime |  | TimestampRes | TimestampRes |
| date |  | integer |  |
| day |  | integer |  |
| hours |  | integer |  |
| minutes |  | integer |  |
| month |  | integer |  |
| nanos |  | integer |  |
| seconds |  | integer |  |
| time |  | integer |  |
| timezoneOffset |  | integer |  |
| year |  | integer |  |
| comMeasureWaterLevel | 比测水位(m) | number(double) |  |
| dataSources | 数据来源: 0-设备计算，1-系统插补，2-设备插补 | integer(int32) |  |
| deviceCode | 设备码 | string |  |
| eliminate | 原始水位状态，0-正常水位，1-异常水位 | integer(int32) |  |
| endTime |  | TimestampRes | TimestampRes |
| date |  | integer |  |
| day |  | integer |  |
| hours |  | integer |  |
| minutes |  | integer |  |
| month |  | integer |  |
| nanos |  | integer |  |
| seconds |  | integer |  |
| time |  | integer |  |
| timezoneOffset |  | integer |  |
| year |  | integer |  |
| imageWaterLevel | 水位(m) | number(double) |  |
| label | 标签 | string |  |
| limit1 |  | integer(int64) |  |
| limit2 |  | integer(int64) |  |
| measureTime | 时间 | TimestampRes | TimestampRes |
| date |  | integer |  |
| day |  | integer |  |
| hours |  | integer |  |
| minutes |  | integer |  |
| month |  | integer |  |
| nanos |  | integer |  |
| seconds |  | integer |  |
| time |  | integer |  |
| timezoneOffset |  | integer |  |
| year |  | integer |  |
| measureTimeList |  | array | string |
| nsbdConfig | 水尺配置 | NsbdConfig | NsbdConfig |
| bottomWaterLevelHeight | 刻度尺最低量程 | number |  |
| bottomWaterLevelPointy | 刻度尺最低量程y坐标 | number |  |
| dynamicWaterLevel | 输出动态水位值 | number |  |
| dynamicWaterLevelPointy | 输出动态水位y坐标 | number |  |
| topWaterLevelHeight | 刻度尺最高量程 | number |  |
| topWaterLevelPointy | 刻度尺最高量程y坐标 | number |  |
| virtualGaugePoints | 水尺坐标 | VirtualGaugePoints | VirtualGaugePoints |
| p1Gauge | 水尺1x坐标 | number |  |
| p2Gauge | 水尺2x坐标 | number |  |
| p3Gauge | 水尺3x坐标 | number |  |
| p4Gauge | 水尺4x坐标 | number |  |
| zeroPointHeight | 刻度尺零点高程 | number |  |
| originalTag | 原始标签: 0-正常，1-异常 | integer(int32) |  |
| originalWaterLevel | 原始水位(m) | number(double) |  |
| pictureUrl | 结果数据地址 | string |  |
| pointNum | 预置点位 | integer(int32) |  |
| rawDataUrl | 原始数据地址，视频或图片 | string |  |
| remarks | 备注 | string |  |
| reportLevel | 上报水位(m) | number(double) |  |
| stationCode | 水文站站码 | string |  |
| stationName | 站点名称 | string |  |
| uploadStatus | 上报状态，0未上报，1为已上报 | integer(int32) |  |
| version | 设备程序版本 | string |  |
| msg |  | string |  |
| pageInfo |  | 分页信息 | 分页信息 |
| current | 当前页码号 | integer(int64) |  |
| pages | 共有多少页 | integer(int64) |  |
| size | 每页条数 | integer(int64) |  |
| total | 总条数 | integer(int64) |  |

## 3.6：第三方水位原始数据（比测）（对应表序号6）

请求地址:https://aiflow2.dashuiyun.cn:9999/prod-api/third/compareMeasureDataPage

参数示例:

```json
{
    "count": 99999,
    "page": 1,
    "request": {
        "stationCode": "00620",
        "deviceCode": "WD000808341771",
        "beginTime": "2025-05-12 00:00:00.213",
        "endTime": "2025-05-19 23:59:59.213"
    }
}
```

描述：

| 参数名称 | 参数说明 | 请求类型 | 是否必须 | 数据类型 | schema |
| --- | --- | --- | --- | --- | --- |
| 请求参数体«OriginalDataLevelThirdDto» | 请求参数体 | body | true | 请求参数体«OriginalDataLevelThirdDto» | 请求参数体«OriginalDataLevelThirdDto» |
| count | 每页条数，默认为10,示例值(10) |  | false | integer(int32) |  |
| page | 页数，第几页，默认为1,示例值(1) |  | false | integer(int32) |  |
| request | 自定义入参 |  | false | OriginalDataLevelThirdDto | OriginalDataLevelThirdDto |
| beginTime | 开始时间：yyyy-MM-dd HH:mm:ss.SSS |  | true | string |  |
| deviceCode | 设备码 |  | false | string |  |
| endTime | 结束时间：yyyy-MM-dd HH:mm:ss.SSS |  | true | string |  |
| stationCode | 水文站站码 |  | false | string |  |

返回示例：

```json
{
	"code": 0,
	"data": [
		{
			"deviceCode": "",
			"measureTime": "",
			"receiveTime": "",
			"stationCode": "",
			"waterFlow": 0,
			"waterLevel": 0
		}
	],
	"msg": "",
	"pageInfo": {
		"current": 0,
		"pages": 0,
		"size": 0,
		"total": 0
	}
}
```

| 参数名称 | 参数说明 | 类型 | schema |
| --- | --- | --- | --- |
| code |  | integer(int32) | integer(int32) |
| data |  | array | OriginalDataLevelThirdVo |
| deviceCode | 设备码 | string |  |
| measureTime | 观测时间 | string |  |
| receiveTime | 接收时间 | string |  |
| stationCode | 水文站站码 | string |  |
| waterFlow | 流量(m3/s) | number(double) |  |
| waterLevel | 水位(m) | number(double) |  |
| msg |  | string |  |
| pageInfo |  | 分页信息 | 分页信息 |
| current | 当前页码号 | integer(int64) |  |
| pages | 共有多少页 | integer(int64) |  |
| size | 每页条数 | integer(int64) |  |
| total | 总条数 | integer(int64) |  |

## 3.7：测流设备原始数据示范案例（对应表序号7）

无功能：暂无接口

## 3.8：图像水位原始数据示范案例（对应表序号8）

无功能：暂无接口

## 3.9：站点流量（对应表序号9）

请求地址: https://aiflow2.dashuiyun.cn:9999/prod-api/flow/reportDataPage

参数示例:

```json
{
  "count": 10,
  "page": 1,
  "request": {
    "beginTime": "",
    "endTime": "",
    "isMedia": 0,
    "measureResult": 0,
    "stationCode": ""
  }
}
```

描述：

| 参数名称 | 参数说明 | 请求类型 | 是否必须 | 数据类型 | schema |
| --- | --- | --- | --- | --- | --- |
| 请求参数体«ReportDataQueryDto» | 请求参数体 | body | true | 请求参数体«ReportDataQueryDto» | 请求参数体«ReportDataQueryDto» |
| count | 每页条数，默认为10,示例值(10) |  | false | integer(int32) |  |
| page | 页数，第几页，默认为1,示例值(1) |  | false | integer(int32) |  |
| request | 自定义入参 |  | false | ReportDataQueryDto | ReportDataQueryDto |
| beginTime | 开始时间：yyyy-MM-dd HH:mm:ss.SSS |  | true | string |  |
| endTime | 结束时间：yyyy-MM-dd HH:mm:ss.SSS |  | true | string |  |
| isMedia | 是否需要视频地址: 0-不需要; 1-需要 |  | false | integer |  |
| measureResult | 测量结果(缺省时默认为1):0-失败,1-成功,2-全部 |  | false | integer |  |
| stationCode | 站码 |  | true | string |  |

返回示例：

```json
{
	"code": 0,
	"data": [
		{
			"beginTime": {
				"date": 0,
				"day": 0,
				"hours": 0,
				"minutes": 0,
				"month": 0,
				"nanos": 0,
				"seconds": 0,
				"time": 0,
				"timezoneOffset": 0,
				"year": 0
			},
			"dataSource": 0,
			"deviceCode": "",
			"endTime": {
				"date": 0,
				"day": 0,
				"hours": 0,
				"minutes": 0,
				"month": 0,
				"nanos": 0,
				"seconds": 0,
				"time": 0,
				"timezoneOffset": 0,
				"year": 0
			},
			"failureType": 0,
			"isHaveSpeedLine": 0,
			"limit1": 0,
			"limit2": 0,
			"measureResult": 0,
			"measureTime": {
				"date": 0,
				"day": 0,
				"hours": 0,
				"minutes": 0,
				"month": 0,
				"nanos": 0,
				"seconds": 0,
				"time": 0,
				"timezoneOffset": 0,
				"year": 0
			},
			"measureTimeList": [],
			"pictureUrl": "",
			"stationCode": "",
			"stationName": "",
			"videoUrls": [
				{
					"cameraIndex": 0,
					"videoIndex": 0,
					"videoUrl": ""
				}
			],
			"waterFlow": 0,
			"waterLevel": 0,
			"waterVelocity": 0,
			"waterYield": 0
		}
	],
	"msg": "",
	"pageInfo": {
		"current": 0,
		"pages": 0,
		"size": 0,
		"total": 0
	}
}
```

| 参数名称 | 参数说明 | 类型 | schema |
| --- | --- | --- | --- |
| code |  | integer(int32) | integer(int32) |
| data |  | array | StationFlow对象 |
| beginTime |  | Timestamp | Timestamp |
| date |  | integer |  |
| day |  | integer |  |
| hours |  | integer |  |
| minutes |  | integer |  |
| month |  | integer |  |
| nanos |  | integer |  |
| seconds |  | integer |  |
| time |  | integer |  |
| timezoneOffset |  | integer |  |
| year |  | integer |  |
| dataSource | 数据来源 0-设备,1-率定工具,2-导入,3-AI预测 | integer(int32) |  |
| deviceCode | 设备码 | string |  |
| endTime |  | Timestamp | Timestamp |
| date |  | integer |  |
| day |  | integer |  |
| hours |  | integer |  |
| minutes |  | integer |  |
| month |  | integer |  |
| nanos |  | integer |  |
| seconds |  | integer |  |
| time |  | integer |  |
| timezoneOffset |  | integer |  |
| year |  | integer |  |
| failureType | 失败类型 1：视频采集失败；2-无水位数据；3-场景识别失败 | integer(int32) |  |
| isHaveSpeedLine | 是否有测速线 0-无,1-有 | integer(int32) |  |
| limit1 |  | integer(int64) |  |
| limit2 |  | integer(int64) |  |
| measureResult | 测量结果，0-失败，1-成功 | integer(int32) |  |
| measureTime | 时间 | Timestamp | Timestamp |
| date |  | integer |  |
| day |  | integer |  |
| hours |  | integer |  |
| minutes |  | integer |  |
| month |  | integer |  |
| nanos |  | integer |  |
| seconds |  | integer |  |
| time |  | integer |  |
| timezoneOffset |  | integer |  |
| year |  | integer |  |
| measureTimeList |  | array | string |
| pictureUrl | 水位结果图片或视频 | string |  |
| stationCode | 水文站站码 | string |  |
| stationName | 站点名称 | string |  |
| videoUrls | 视频地址 | array | CameraVideoFile |
| cameraIndex | 摄像头序号 | integer |  |
| videoIndex | 视频序号 | integer |  |
| videoUrl | 视频地址 | string |  |
| waterFlow | 流量(m3/s) | number(double) |  |
| waterLevel | 水位(m) | number(double) |  |
| waterVelocity | 流速(m/s) | number(double) |  |
| waterYield | 水量(万立方米) | number(double) |  |
| msg |  | string |  |
| pageInfo |  | 分页信息 | 分页信息 |
| current | 当前页码号 | integer(int64) |  |
| pages | 共有多少页 | integer(int64) |  |
| size | 每页条数 | integer(int64) |  |
| total | 总条数 | integer(int64) |  |

## 3.10：站点流量测速线（对应表序号10）

请求地址：https://aiflow2.dashuiyun.cn:9999/prod-api/flow/stationSpeedLineDistribution

参数示例:

```json
{
    "stationCode": "00319",
    "measureTime": "2025-05-19 16:00:00.000"
}
```

描述：

| 参数名称 | 参数说明 | 请求类型 | 是否必须 | 数据类型 | schema |
| --- | --- | --- | --- | --- | --- |
| stationSpeedLineQuery | 断面流速分布查询参数 | body | true | StationSpeedLineQuery | StationSpeedLineQuery |
| measureTime | 观测时间 |  | false | string |  |
| stationCode | 水文站站码 |  | false | string |  |

返回示例：

```json
{
	"code": 0,
	"data": {
		"deviceVideoInfoVo": {
			"videoHeight": 0,
			"videoWith": 0
		},
		"measureTime": "",
		"sectionPointVos": [
			{
				"elevation": 0,
				"startDistance": 0
			}
		],
		"stationFlowSpeedLines": [
			{
				"deviceCode": "",
				"lineNum": 0,
				"measureTime": {
					"date": 0,
					"day": 0,
					"hours": 0,
					"minutes": 0,
					"month": 0,
					"nanos": 0,
					"seconds": 0,
					"time": 0,
					"timezoneOffset": 0,
					"year": 0
				},
				"srcEndPixX": 0,
				"srcEndPixY": 0,
				"srcFlowVelocity": 0,
				"srcStartPixX": 0,
				"srcStartPixY": 0,
				"startPointDistance": 0,
				"stationCode": "",
				"vlineDataSource": 0,
				"vlineDepth": 0,
				"vlineExpressArea": 0,
				"vlineExpressFlow": 0,
				"vlineTransParas": 0
			}
		],
		"waterFlow": 0,
		"waterLevel": 0,
		"waterVelocity": 0
	},
	"msg": "",
	"pageInfo": {
		"current": 0,
		"pages": 0,
		"size": 0,
		"total": 0
	}
}
```

| 参数名称 | 参数说明 | 类型 | schema |
| --- | --- | --- | --- |
| code |  | integer(int32) | integer(int32) |
| data |  | StationSpeedLineDistribution | StationSpeedLineDistribution |
| deviceVideoInfoVo | 设备视频信息 | DeviceVideoInfoVo | DeviceVideoInfoVo |
| videoHeight | 视频高 | integer |  |
| videoWith | 视频宽 | integer |  |
| measureTime | 时间 | string |  |
| sectionPointVos | 断面图信息 | array | SectionPointVo |
| elevation | 水位高程 | number |  |
| startDistance | 左岸起点距 | number |  |
| stationFlowSpeedLines | 测速线数据 | array | StationFlowSpeedLine |
| deviceCode | 设备码 | string |  |
| lineNum | 测速线编号 | integer |  |
| measureTime | 时间 | Timestamp | Timestamp |
| srcEndPixX | 终点X坐标 | number |  |
| srcEndPixY | 终点Y坐标 | number |  |
| srcFlowVelocity | 测速线表面流速(m/s) | number |  |
| srcStartPixX | 起点X坐标 | number |  |
| srcStartPixY | 起点Y坐标 | number |  |
| startPointDistance | 测速线起点距(m) | number |  |
| stationCode | 水文站站码 | string |  |
| vlineDataSource | 测速线表面流速类型: 0代表插值，1代表算法给出 | integer |  |
| vlineDepth | 测速线水深(m) | number |  |
| vlineExpressArea | 测速线面积(m2) | number |  |
| vlineExpressFlow | 测速线部分流量(m3/s) | number |  |
| vlineTransParas | 测速线转换系数 | number |  |
| waterFlow | 流量(m3/s) | number(double) |  |
| waterLevel | 水位(m) | number(double) |  |
| waterVelocity | 流速(m/s) | number(double) |  |
| msg |  | string |  |
| pageInfo |  | 分页信息 | 分页信息 |
| current | 当前页码号 | integer(int64) |  |
| pages | 共有多少页 | integer(int64) |  |
| size | 每页条数 | integer(int64) |  |
| total | 总条数 | integer(int64) |  |

## 3.11：站点水位（对应表序号11）

请求地址:https://aiflow2.dashuiyun.cn:9999/prod-api/level/reportDataPage

参数示例:

```json
{
  "count": 10,
  "page": 1,
  "request": {
    "beginTime": "",
    "endTime": "",
    "isMedia": 0,
    "measureResult": 0,
    "stationCode": ""
  }
}
```

描述：

| 参数名称 | 参数说明 | 请求类型 | 是否必须 | 数据类型 | schema |
| --- | --- | --- | --- | --- | --- |
| 请求参数体«ReportDataQueryDto» | 请求参数体 | body | true | 请求参数体«ReportDataQueryDto» | 请求参数体«ReportDataQueryDto» |
| count | 每页条数，默认为10,示例值(10) |  | false | integer(int32) |  |
| page | 页数，第几页，默认为1,示例值(1) |  | false | integer(int32) |  |
| request | 自定义入参 |  | false | ReportDataQueryDto | ReportDataQueryDto |
| beginTime | 开始时间：yyyy-MM-dd HH:mm:ss.SSS |  | true | string |  |
| endTime | 结束时间：yyyy-MM-dd HH:mm:ss.SSS |  | true | string |  |
| isMedia | 是否需要视频地址: 0-不需要; 1-需要 |  | false | integer |  |
| measureResult | 测量结果(缺省时默认为1):0-失败,1-成功,2-全部 |  | false | integer |  |
| stationCode | 站码 |  | true | string |  |

返回示例：

```json
{
	"code": 0,
	"data": [
		{
			"beginTime": {
				"date": 0,
				"day": 0,
				"hours": 0,
				"minutes": 0,
				"month": 0,
				"nanos": 0,
				"seconds": 0,
				"time": 0,
				"timezoneOffset": 0,
				"year": 0
			},
			"dataSource": 0,
			"deviceCode": "",
			"endTime": {
				"date": 0,
				"day": 0,
				"hours": 0,
				"minutes": 0,
				"month": 0,
				"nanos": 0,
				"seconds": 0,
				"time": 0,
				"timezoneOffset": 0,
				"year": 0
			},
			"failureType": 0,
			"limit1": 0,
			"limit2": 0,
			"measureResult": 0,
			"measureTime": {
				"date": 0,
				"day": 0,
				"hours": 0,
				"minutes": 0,
				"month": 0,
				"nanos": 0,
				"seconds": 0,
				"time": 0,
				"timezoneOffset": 0,
				"year": 0
			},
			"measureTimeList": [],
			"nsbdConfig": {
				"bottomWaterLevelHeight": 0,
				"bottomWaterLevelPointy": 0,
				"dynamicWaterLevel": 0,
				"dynamicWaterLevelPointy": 0,
				"topWaterLevelHeight": 0,
				"topWaterLevelPointy": 0,
				"virtualGaugePoints": {
					"p1Gauge": 0,
					"p2Gauge": 0,
					"p3Gauge": 0,
					"p4Gauge": 0
				},
				"zeroPointHeight": 0
			},
			"pictureUrl": "",
			"rawDataUrl": "",
			"stationCode": "",
			"stationName": "",
			"waterLevel": 0
		}
	],
	"msg": "",
	"pageInfo": {
		"current": 0,
		"pages": 0,
		"size": 0,
		"total": 0
	}
}
```

描述：

| 参数名称 | 参数说明 | 类型 | schema |
| --- | --- | --- | --- |
| code |  | integer(int32) | integer(int32) |
| data |  | array | StationLevel对象 |
| beginTime |  | TimestampRes | TimestampRes |
| date |  | integer |  |
| day |  | integer |  |
| hours |  | integer |  |
| minutes |  | integer |  |
| month |  | integer |  |
| nanos |  | integer |  |
| seconds |  | integer |  |
| time |  | integer |  |
| timezoneOffset |  | integer |  |
| year |  | integer |  |
| dataSource |  | integer(int32) |  |
| deviceCode | 设备码 | string |  |
| endTime |  | TimestampRes | TimestampRes |
| date |  | integer |  |
| day |  | integer |  |
| hours |  | integer |  |
| minutes |  | integer |  |
| month |  | integer |  |
| nanos |  | integer |  |
| seconds |  | integer |  |
| time |  | integer |  |
| timezoneOffset |  | integer |  |
| year |  | integer |  |
| failureType |  | integer(int32) |  |
| limit1 |  | integer(int64) |  |
| limit2 |  | integer(int64) |  |
| measureResult |  | integer(int32) |  |
| measureTime | 时间 | TimestampRes | TimestampRes |
| date |  | integer |  |
| day |  | integer |  |
| hours |  | integer |  |
| minutes |  | integer |  |
| month |  | integer |  |
| nanos |  | integer |  |
| seconds |  | integer |  |
| time |  | integer |  |
| timezoneOffset |  | integer |  |
| year |  | integer |  |
| measureTimeList |  | array | string |
| nsbdConfig | 水尺配置 | NsbdConfig | NsbdConfig |
| bottomWaterLevelHeight | 刻度尺最低量程 | number |  |
| bottomWaterLevelPointy | 刻度尺最低量程y坐标 | number |  |
| dynamicWaterLevel | 输出动态水位值 | number |  |
| dynamicWaterLevelPointy | 输出动态水位y坐标 | number |  |
| topWaterLevelHeight | 刻度尺最高量程 | number |  |
| topWaterLevelPointy | 刻度尺最高量程y坐标 | number |  |
| virtualGaugePoints | 水尺坐标 | VirtualGaugePoints | VirtualGaugePoints |
| p1Gauge | 水尺1x坐标 | number |  |
| p2Gauge | 水尺2x坐标 | number |  |
| p3Gauge | 水尺3x坐标 | number |  |
| p4Gauge | 水尺4x坐标 | number |  |
| zeroPointHeight | 刻度尺零点高程 | number |  |
| pictureUrl | 图片地址 | string |  |
| rawDataUrl |  | string |  |
| stationCode | 水文站站码 | string |  |
| stationName | 站点名称 | string |  |
| waterLevel | 水位(m) | number(double) |  |
| msg |  | string |  |
| pageInfo |  | 分页信息 | 分页信息 |
| current | 当前页码号 | integer(int64) |  |
| pages | 共有多少页 | integer(int64) |  |
| size | 每页条数 | integer(int64) |  |
| total | 总条数 | integer(int64) |  |
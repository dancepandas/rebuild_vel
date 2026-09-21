from PIL import Image
import json, glob, os

sizes = {}
for f in glob.glob('runs/v1/report_figs/*.png') + glob.glob('runs/v1_mse/report_figs/*.png'):
    key = f.replace(os.sep, '/')
    sizes[key] = Image.open(f).size
json.dump(sizes, open('runs/v1/report_figs/sizes.json', 'w'))
print(len(sizes), 'entries, sample:', next(iter(sizes)))

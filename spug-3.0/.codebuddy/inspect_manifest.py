import json
from collections import Counter

p = '/data/backups/tdyw/backup_sets/backup_set_20260724_020501/manifest.json'
m = json.load(open(p, encoding='utf-8'))
d = m['filesets']['documents']

print('=== 0724 backup_set documents stats ===')
print('file_count:', d.get('file_count'))
print('directory_count:', d.get('directory_count'))
print('archive_size:', d.get('archive_size'))

files = d.get('files', [])
print('files_len_in_manifest:', len(files))

chunk_in_path = [f for f in files if 'chunk_' in f.get('relative_path', '')]
bin_files = [f for f in files if f.get('relative_path', '').endswith('.bin')]
part_files = [f for f in files if f.get('relative_path', '').endswith('.part')]
print('chunk_in_path_count:', len(chunk_in_path))
print('bin_count:', len(bin_files))
print('part_count:', len(part_files))

print('--- first 10 relative_paths ---')
for f in files[:10]:
    print(f.get('relative_path'), f.get('size'))

print('--- extension distribution (top 15) ---')
exts = Counter()
for f in files:
    rp = f.get('relative_path', '')
    ext = rp.rsplit('.', 1)[-1].lower() if '.' in rp else 'NO_EXT'
    exts[ext] += 1
for ext, c in exts.most_common(15):
    print(f'  {ext}: {c}')

if chunk_in_path:
    print('--- sample chunk_ paths ---')
    for f in chunk_in_path[:5]:
        print(f.get('relative_path'), f.get('size'))

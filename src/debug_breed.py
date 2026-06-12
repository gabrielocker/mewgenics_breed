import sqlite3, sys
sys.path.insert(0, 'src')
from extract_data import lz4_decompress_block

conn = sqlite3.connect(r'save\steamcampaign01.sav')
c = conn.cursor()

for cat_id in [1, 5]:
    c.execute('SELECT data FROM cats WHERE key=?', (cat_id,))
    blob = c.fetchone()[0]
    sz = int.from_bytes(blob[:4], 'little')
    dec = lz4_decompress_block(blob[4:], sz)
    
    print(f"Cat #{cat_id}: buscando breed (raw vs decompressed)")
    for term in [b'pint', b'pdex', b'int']:
        pr = blob.find(term)
        pd = dec.find(term)
        print(f"  '{term.decode()}': raw={pr}, dec={pd}")
conn.close()

print()
print('Byte before int:', hex(dec[pos-1]), '=', repr(chr(dec[pos-1]) if 32<=dec[pos-1]<127 else '?'))
conn.close()

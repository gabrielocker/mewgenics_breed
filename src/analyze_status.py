import sqlite3, struct

conn = sqlite3.connect(r'save\steamcampaign01.sav')
c = conn.cursor()

c.execute("SELECT data FROM files WHERE key='house_state';")
blob = c.fetchone()[0]

print("=== HEX dump of house_state (first 400 bytes) ===")
for i in range(0, min(400, len(blob)), 32):
    hex_str = ' '.join(f'{b:02x}' for b in blob[i:i+32])
    ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in blob[i:i+32])
    print(f"  {i:04x}: {hex_str:<96s} {ascii_str}")

conn.close()







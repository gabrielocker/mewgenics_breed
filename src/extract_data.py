"""
Mewgenics Save File Extractor v2
Extracts cat data from .sav SQLite database files into structured JSON.
Uses LZ4 decompression + proper binary offsets from mewgenics-save-editor.
"""
import sqlite3
import struct
import json
import os
import sys


# ===================== LZ4 Decompression =====================
def lz4_decompress_block(src, dst_size):
    dst = bytearray(dst_size)
    src_pos, dst_pos = 0, 0
    src_len = len(src)
    while src_pos < src_len and dst_pos < dst_size:
        token = src[src_pos]; src_pos += 1
        lit_len = (token >> 4) & 0x0f; match_len = token & 0x0f
        if lit_len == 15:
            while src_pos < src_len and src[src_pos] == 255:
                lit_len += 255; src_pos += 1
            if src_pos >= src_len: break
            lit_len += src[src_pos]; src_pos += 1
        if src_pos + lit_len > src_len: lit_len = src_len - src_pos
        for _ in range(lit_len):
            if dst_pos >= dst_size: break
            dst[dst_pos] = src[src_pos]; dst_pos += 1; src_pos += 1
        if src_pos >= src_len or dst_pos >= dst_size: break
        if src_pos + 2 > src_len: break
        match_off = src[src_pos] | (src[src_pos + 1] << 8); src_pos += 2
        if match_off == 0 or match_off > dst_pos: break
        mlen = match_len + 4
        if match_len == 15:
            while src_pos < src_len and src[src_pos] == 255:
                mlen += 255; src_pos += 1
            if src_pos < src_len: mlen += src[src_pos]; src_pos += 1
        for _ in range(mlen):
            if dst_pos >= dst_size: break
            dst[dst_pos] = dst[dst_pos - match_off]; dst_pos += 1
    return bytes(dst)


def decompress_cat_blob(wrapped):
    """Decompress cat BLOB. First 4 bytes = uncompressed size, rest = LZ4."""
    if len(wrapped) < 4: return wrapped
    uncomp = struct.unpack_from("<I", wrapped, 0)[0]
    stream = wrapped[4:]
    try:
        return lz4_decompress_block(stream, uncomp)
    except: 
        return wrapped


# ===================== Binary Helpers =====================
def u16(b, o): return struct.unpack_from("<H", b, o)[0]
def u32(b, o): return struct.unpack_from("<I", b, o)[0]
def u64(b, o): return struct.unpack_from("<Q", b, o)[0]


def parse_house_state(blob):
    """Parse house_state blob, returns dict of {cat_key: room_name}."""
    if not blob or len(blob) < 8:
        return {}
    ver = u32(blob, 0)
    cnt = u32(blob, 4)
    if ver != 0 or cnt > 512:
        return {}
    off = 8
    cats = {}
    for _ in range(cnt):
        if off + 16 > len(blob):
            break
        key = u32(blob, off)
        room_len = u64(blob, off + 8)
        name_off = off + 16
        if name_off + room_len > len(blob):
            break
        room = blob[name_off:name_off + room_len].decode("ascii", errors="replace")
        d_off = name_off + room_len
        if d_off + 24 > len(blob):
            break
        cats[key] = room
        off = d_off + 24
    return cats


def parse_adventure_state(blob):
    """Parse adventure_state blob, returns list of cat keys."""
    if not blob or len(blob) < 8:
        return []
    ver = u32(blob, 0)
    cnt = u32(blob, 4)
    if cnt > 8:
        return []
    off = 8
    keys = []
    for _ in range(cnt):
        if off + 8 > len(blob):
            break
        v = u64(blob, off)
        off += 8
        hi = (v >> 32) & 0xFFFFFFFF
        lo = v & 0xFFFFFFFF
        key = int(hi if hi != 0 else lo)
        if 0 < key <= 1000000:
            keys.append(key)
    return keys


SEX_MAP = {0: "Male", 1: "Female", 2: "Ditto"}
STAT_NAMES = ["STR", "DEX", "CON", "INT", "SPD", "CHA", "LUCK"]

CLASS_PATTERNS = {
    'Fighter': ['Fighter', 'BasicMelee_Fighter'],
    'Hunter': ['Hunter', 'BasicRanged_Hunter'],
    'Mage': ['Mage', 'DMage', 'TMage', 'AMage', 'MageTeleport'],
    'Medic': ['Medic', 'BasicMed'], 'Necromancer': ['Necromancer'],
    'Tank': ['Tank', 'BasicTankMelee'],
    'Thief': ['Thief', 'BasicStraightShot_Thief'],
    'Colorless': ['Colorless'],
}


# ===================== Mutation / Genealogy =====================
MUTATION_SLOT_MAP = {
    0: "body", 1: "bodyFur", 5: "head", 6: "headFur",
    10: "tail", 11: "tailFur", 15: "legL", 16: "legLFur",
    20: "legR", 21: "legRFur", 25: "armL", 26: "armLFur",
    30: "armR", 31: "armRFur", 35: "eyeL", 36: "eyeLFur",
    40: "eyeR", 41: "eyeRFur", 45: "eyebrowL", 46: "eyebrowLFur",
    50: "eyebrowR", 51: "eyebrowRFur", 55: "earL", 56: "earLFur",
    60: "earR", 61: "earRFur", 65: "mouth", 66: "mouthFur",
}

MARKER_EXTRA_OFFSET = 8
KNOWN_TAGS = [(b'int\x02', 4), (b'star2', 5)]


def has_marker_at_name_end(dec, name_end):
    if name_end + 4 > len(dec):
        return False
    return u32(dec, name_end) != 0


def get_extra_offset_for_marker(dec, name_end):
    return MARKER_EXTRA_OFFSET if has_marker_at_name_end(dec, name_end) else 0


def get_tag_offset(dec, name_end, marker):
    tag_start = name_end + 8 if marker != 0 else name_end
    if tag_start + 8 > len(dec):
        return 0
    for sig, size in KNOWN_TAGS:
        if dec[tag_start:tag_start + len(sig)] == sig:
            return size
    return 0


def get_total_extra_offset(dec, name_end):
    if name_end + 4 > len(dec):
        return 0
    marker = u32(dec, name_end)
    total = 0
    if marker != 0:
        total += 8
    total += get_tag_offset(dec, name_end, marker)
    return total


def get_t_array_start(dec, name_end):
    extra = get_total_extra_offset(dec, name_end)
    base = name_end + 0x74 + extra
    if base + 4 > len(dec):
        return base
    best_offset = base
    best_score = -1
    check_indices = [0, 1, 5, 6, 10, 11, 15, 16, 20, 21, 25, 26, 30, 31, 35, 36, 40, 41]
    for delta in range(-8, 12):
        offset = base + delta
        if offset < 0:
            continue
        valid = True
        for i in check_indices:
            if offset + i * 4 + 4 > len(dec):
                valid = False
                break
        if not valid:
            continue
        score = 0
        for i in check_indices:
            val = u32(dec, offset + i * 4)
            if val == 0:
                score += 1
            elif 2 <= val <= 1000:
                score += 3
            elif val < 500000:
                score += 2
        if score > best_score:
            best_score = score
            best_offset = offset
    return best_offset


def read_mutations(dec, name_end):
    """Read T-array mutations from cat blob. Returns {slot_idx: value}."""
    mutations = {}
    t_start = get_t_array_start(dec, name_end)
    for idx in MUTATION_SLOT_MAP:
        offset = t_start + idx * 4
        if offset + 4 > len(dec):
            continue
        val = u32(dec, offset)
        if val > 1:  # Only non-default
            mutations[idx] = val
    return mutations


# ===================== Pedigree / Genealogy =====================
def parse_pedigree(db_path):
    """Parse pedigree from save file. Returns {child_id: [parent1_id, parent2_id]}."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        row = conn.execute("SELECT data FROM files WHERE key='pedigree'").fetchone()
        conn.close()
        if not row or not row[0]:
            return {}, set()
        blob = row[0] if isinstance(row[0], bytes) else bytes(row[0])
    except Exception:
        return {}, set()
    
    # Extract entries: [cat_id(u32), flag(u32)] = 8 bytes each
    entries = []
    for off in range(0, len(blob) - 7, 8):
        cid = u32(blob, off)
        if 1 <= cid <= 10000:
            entries.append((off, cid))
    
    # Group consecutive entries (gap <= 8 bytes → same group)
    groups = [[entries[0][1]]]
    for i in range(1, len(entries)):
        if entries[i][0] - entries[i-1][0] <= 8:
            groups[-1].append(entries[i][1])
        else:
            groups.append([entries[i][1]])
    
    # Groups of 3 = [child, parent1, parent2]
    parent_map = {}
    all_pairs = set()
    for g in groups:
        if len(g) == 3:
            child, p1, p2 = g
            if child not in parent_map:
                parent_map[child] = [p1, p2]
        # All consecutive pairs in any group = breeding pairs
        for i in range(len(g) - 1):
            a, b = g[i], g[i+1]
            if a != b:
                all_pairs.add(tuple(sorted([a, b])))
    
    return parent_map, all_pairs


# ===================== Cat Extraction =====================
def extract_cat_data(wrapped_blob, cat_id):
    dec = decompress_cat_blob(wrapped_blob)
    cat = {'id': cat_id, 'blob_size': len(wrapped_blob), 'dec_size': len(dec)}

    # --- Name & Sex ---
    name, sex, name_end = f"Cat_{cat_id}", "Unknown", 0x14
    for off_len in (0x0C, 0x10):
        if off_len + 4 > len(dec): continue
        nl = u32(dec, off_len)
        if not (0 < nl <= 128): continue
        start = 0x14; end = start + nl * 2
        if end > len(dec): continue
        try: name = dec[start:end].decode("utf-16le", errors="replace").rstrip("\x00")
        except: continue
        if not name: continue
        name_end = end
        marker = u32(dec, name_end) if name_end + 4 <= len(dec) else 0
        extra = 8 if marker != 0 else 0
        oa, ob = name_end + 8 + extra, name_end + 12 + extra
        if ob + 2 <= len(dec):
            a, b = u16(dec, oa), u16(dec, ob)
            if a == b and a in SEX_MAP: sex = SEX_MAP[a]
            elif a in SEX_MAP: sex = SEX_MAP[a]
            elif b in SEX_MAP: sex = SEX_MAP[b]
        break
    cat['name'], cat['gender'], cat['name_end'] = name, sex, name_end

    # --- Status Flags ---
    marker = u32(dec, name_end) if name_end + 4 <= len(dec) else 0
    flags = (marker & 0xFFFF) if marker != 0 else (
        u16(dec, name_end + 0x10) if name_end + 0x12 <= len(dec) else 0)
    dead = bool(flags & 0x0020)
    donated = bool(flags & 0x4000)
    retired = bool(flags & 0x0002)
    is_old = bool(flags & 0x0100)
    # Status: Dead is the primary status. Alive cats may have retired/donated as substatus.
    if dead:
        cat['status'] = 'Dead'
    elif donated:
        cat['status'] = 'Dead'  # Donated cats are gone from your house
    else:
        cat['status'] = 'Alive'
    cat['is_dead'] = dead
    cat['is_donated'] = donated
    cat['is_retired'] = retired
    cat['is_old'] = is_old
    # "available" means the cat can breed (active + alive, not dead, not donated)
    cat['available'] = False  # Will be set after we know is_active
    cat['flags_raw'] = f'0x{flags:04x}'

    # --- Base Stats (range 1-7 in Mewgenics) ---
    stats = {}
    n = len(dec); best_score = -1e18
    for off in range(max(0, 0x1CC - 0x140), min(n - 28, 0x1CC + 0x140)):
        vals = struct.unpack_from("<7i", dec, off)
        if any(v < 1 or v > 7 for v in vals): continue
        dist = abs(off - 0x1CC); s = sum(vals)
        score = (1000 - dist) + s * 0.1
        if score > best_score: best_score = score; stats = dict(zip(STAT_NAMES, vals))
    if stats:
        cat['stats'] = stats
        cat['stat_total'] = sum(stats.values())
        cat['stat7_count'] = sum(1 for v in stats.values() if v == 7)
        cat['stat7_list'] = [k for k, v in stats.items() if v == 7]

    # --- Strings from decompressed blob ---
    strings = []; current = bytearray()
    for b in dec:
        if 32 <= b < 127: current.append(b)
        elif len(current) >= 2: strings.append(current.decode('ascii', errors='replace')); current = bytearray()
    if len(current) >= 2: strings.append(current.decode('ascii', errors='replace'))
    cat['all_strings'] = strings

    # --- Class ---
    found = []
    for s in strings:
        for cn, pats in CLASS_PATTERNS.items():
            if any(p in s for p in pats) and cn not in found: found.append(cn)
    non_c = [c for c in found if c != 'Colorless']
    cat['cat_class'] = non_c[-1] if non_c else ('Colorless' if 'Colorless' in found else 'unknown')

    # --- Breed (search in raw blob - breed codes fragment in decompressed) ---
    vs = ('int','str','dex','con','cha','spd','lck')
    vp = {'p':'Primary','s':'Secondary','t':'Tertiary','v':'Variant'}
    breed = None
    # First try decompressed blob for full breed strings
    for s in strings:
        if 3 <= len(s) <= 5 and s[0] in ('p','s','t','v') and s[1:] in vs:
            breed = s; break
    # Fallback: search raw compressed blob (breed codes survive compression intact)
    if not breed:
        for s in vs:
            for prefix in ('p','s','t','v'):
                pos = wrapped_blob.find((prefix + s).encode('ascii'))
                if pos >= 0:
                    breed = prefix + s; break
            if breed: break
    cat['breed_code'] = breed or 'unknown'
    sm = {'int':'Intelligence','str':'Strength','dex':'Dexterity','con':'Constitution','cha':'Charisma','spd':'Speed','lck':'Luck'}
    bc = cat['breed_code']
    cat['stat_focus'] = sm.get(bc[1:], bc[1:]) if bc != 'unknown' and len(bc) >= 2 else 'unknown'
    cat['stat_tier'] = vp.get(bc[0], bc[0]) if bc != 'unknown' and len(bc) >= 2 else 'unknown'

    # --- Abilities ---
    excl = ('@','t','X','D','u','d','a','e','p','v','s','N','G','`','Default','Basic','None','True','False')
    abilities = []
    for s in strings:
        sc = s.rstrip('.,;:!?*#0123456789<>/\\\'\"=+&^%$()[]{}')
        if len(sc) >= 4 and sc[0].isupper() and not any(sc.startswith(p) for p in excl):
            if sc not in abilities: abilities.append(sc)
    ik = ['Hat','Cape','Mask','Belt','Collar','Vial','Generator','Relic','Shield','Armor','Boots','Gloves','Ring','Amulet','Pendant','Charm','Tome','Wand','Staff','Bow','Sword','Axe','Dagger','Claw','Fang']
    items = [s for s in abilities if any(k in s for k in ik)]
    abilities = [s for s in abilities if s not in items]
    cat['abilities'], cat['items'] = abilities, items

    # --- Mutations (genetic fingerprint for kinship detection) ---
    try:
        mutations = read_mutations(dec, name_end)
        cat['mutations'] = mutations
        cat['mutation_count'] = len(mutations)
    except Exception:
        cat['mutations'] = {}
        cat['mutation_count'] = 0
    return cat


def extract_properties(db_path):
    """Extract game properties."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT key, data FROM properties;")
    props = {}
    for key, data in cursor.fetchall():
        props[key] = data
    conn.close()
    return props


# ⚠️ READ-ONLY: points to the real game save file
def find_save_path():
    """Auto-detect the Mewgenics save file location."""
    candidates = [
        # Steam default install
        os.path.join(os.environ.get('PROGRAMFILES(X86)', 'C:\\Program Files (x86)'),
                     'Steam', 'userdata'),
        # Common steam library locations
        os.path.join(os.environ.get('USERPROFILE', 'C:\\Users\\Default'),
                     'AppData', 'Roaming', 'Glaiel Games', 'Mewgenics'),
        # By Steam ID pattern scan
    ]
    
    # Scan AppData for Glaiel Games/Mewgenics/*/saves/*.sav
    appdata = os.path.join(os.environ.get('APPDATA', ''), 'Glaiel Games', 'Mewgenics')
    if os.path.isdir(appdata):
        for entry in os.listdir(appdata):
            saves_dir = os.path.join(appdata, entry, 'saves')
            if os.path.isdir(saves_dir):
                for f in os.listdir(saves_dir):
                    if f.endswith('.sav'):
                        return os.path.join(saves_dir, f)
    
    # Fallback: local copy
    local = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'save', 'steamcampaign01.sav')
    if os.path.exists(local):
        return local
    
    return local  # Last resort

REAL_SAVE_PATH = find_save_path()

# Handle PyInstaller bundling
def _get_data_dir():
    """Get directory for data files (template, icons)."""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(__file__)

def extract_all_cats(db_path):
    """Extract all cats from the save file, marking active (house/adventure) ones."""
    # Use read-only URI mode to guarantee no modifications
    db_uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True)
    cursor = conn.cursor()
    
    # Read house_state and adventure_state to know which cats are "active"
    house_cats = {}
    adventure_keys = []
    try:
        hs_row = conn.execute("SELECT data FROM files WHERE key='house_state'").fetchone()
        if hs_row and hs_row[0]:
            blob = hs_row[0] if isinstance(hs_row[0], bytes) else bytes(hs_row[0])
            house_cats = parse_house_state(blob)
        adv_row = conn.execute("SELECT data FROM files WHERE key='adventure_state'").fetchone()
        if adv_row and adv_row[0]:
            blob = adv_row[0] if isinstance(adv_row[0], bytes) else bytes(adv_row[0])
            adventure_keys = parse_adventure_state(blob)
    except Exception as e:
        print(f"Warning: Could not read house/adventure state: {e}")
    
    # Build location lookup
    location = {}
    for key, room in house_cats.items():
        location[key] = room
    for key in adventure_keys:
        if key not in location:
            location[key] = "(Aventura)"
    
    print(f"Active cats: {len(location)} (House: {len(house_cats)}, Adventure: {len(adventure_keys)})")
    
    cursor.execute("SELECT key, data FROM cats ORDER BY key;")
    cats = []
    for key, blob in cursor.fetchall():
        cat = extract_cat_data(blob, key)
        cat['location'] = location.get(key, None)
        cat['is_active'] = key in location
        # Available = active + not dead + not donated
        cat['available'] = cat['is_active'] and not cat['is_dead'] and not cat['is_donated']
        cats.append(cat)
    conn.close()
    
    # Parse pedigree for genealogy
    parent_map, _ = parse_pedigree(db_path)
    for cat in cats:
        cat['parents'] = parent_map.get(cat['id'], [])
    
    return cats


def build_breeding_insights(cats):
    """Generate breeding insights, focusing on stat-7 complementarity."""
    available = [c for c in cats if c.get('available')]
    
    insights = {
        'total_cats': len(cats),
        'available_cats': len(available),
        'gender_distribution': {},
        'class_distribution': {},
        'breed_distribution': {},
        'stat_focus_distribution': {},
        'ability_frequency': {},
        'rare_abilities': [],
        'compatible_pairs': [],
        'stat7_summary': [],
    }

    all_abilities = []
    for cat in cats:
        g = cat.get('gender', 'Unknown')
        insights['gender_distribution'][g] = insights['gender_distribution'].get(g, 0) + 1
        cl = cat.get('cat_class', 'unknown')
        insights['class_distribution'][cl] = insights['class_distribution'].get(cl, 0) + 1
        bc = cat.get('breed_code', 'unknown')
        insights['breed_distribution'][bc] = insights['breed_distribution'].get(bc, 0) + 1
        sf = f"{cat.get('stat_tier', '?')}_{cat.get('stat_focus', '?')}"
        insights['stat_focus_distribution'][sf] = insights['stat_focus_distribution'].get(sf, 0) + 1
        for ab in cat.get('abilities', []):
            all_abilities.append(ab)
            insights['ability_frequency'][ab] = insights['ability_frequency'].get(ab, 0) + 1

    for ab, count in insights['ability_frequency'].items():
        if count <= 3:
            insights['rare_abilities'].append({'ability': ab, 'count': count})
    insights['rare_abilities'].sort(key=lambda x: x['count'])

    # Stat-7 summary: cats ranked by how many 7s they have
    stat7_cats = sorted(
        [c for c in cats if c.get('stat7_count', 0) > 0],
        key=lambda c: -c['stat7_count']
    )
    for c in stat7_cats[:20]:
        insights['stat7_summary'].append({
            'id': c['id'],
            'name': c['name'],
            'gender': c.get('gender'),
            'stat7_count': c['stat7_count'],
            'stat7_list': c['stat7_list'],
            'stat_total': c.get('stat_total', 0),
            'is_active': c.get('is_active'),
        })

    # --- Breeding pairs: only available cats, stat-7 focused ---
    males = [c for c in available if c.get('gender') == 'Male']
    females = [c for c in available if c.get('gender') == 'Female']
    dittos = [c for c in available if c.get('gender') == 'Ditto']
    
    all_stats = ['STR', 'DEX', 'CON', 'INT', 'SPD', 'CHA', 'LUCK']
    tier_weight = {'p': 4, 's': 3, 't': 2, 'v': 1}

    # Build children map (parent_id → list of child_ids) for descendant lookup
    children_map = {}
    for c in available:
        c_parents = c.get('parents', []) or []
        for p in c_parents:
            if p > 0:
                children_map.setdefault(p, []).append(c['id'])

    def get_descendants(cat_id, depth=2):
        """Get descendant IDs down to N generations."""
        result = set()
        if depth <= 0:
            return result
        kids = children_map.get(cat_id, [])
        for k in kids:
            result.add(k)
            result |= get_descendants(k, depth - 1)
        return result

    def get_ancestors(cat, cat_map, generations=3):
        """Get set of ancestor IDs up to N generations."""
        ancestors = set()
        parents = cat.get('parents', []) or []
        if not parents or len(parents) < 2 or parents == [0, 0]:
            return ancestors
        p1, p2 = parents[0], parents[1]
        if p1 > 0 and p2 > 0:
            ancestors.add(p1)
            ancestors.add(p2)
            if generations > 1:
                gp1 = cat_map.get(p1, {}).get('parents', []) or []
                gp2 = cat_map.get(p2, {}).get('parents', []) or []
                for gp in gp1 + gp2:
                    if gp > 0:
                        ancestors.add(gp)
                        if generations > 2:
                            # Continue up to 3rd generation
                            ggp1 = cat_map.get(gp, {}).get('parents', []) or []
                            for ggp in ggp1:
                                if ggp > 0:
                                    ancestors.add(ggp)
        return ancestors

    def pedigree_relation(a, b, cat_map):
        """Check pedigree relationship between two cats.
        Returns (penalty, label) where label describes the relation.
        """
        a_p = a.get('parents', []) or []
        b_p = b.get('parents', []) or []
        a_id, b_id = a['id'], b['id']
        
        # 1. Direct parent-child
        if a_id in b_p or b_id in a_p:
            return (-25, "PARENT-CHILD")
        
        # 2. Full siblings (same both parents)
        if len(a_p) >= 2 and len(b_p) >= 2 and a_p[0] > 0 and a_p[1] > 0 and b_p[0] > 0 and b_p[1] > 0:
            if sorted(a_p[:2]) == sorted(b_p[:2]):
                return (-20, "FULL SIBLINGS")
        
        # 3. Half-siblings (one shared parent)
        if a_p and b_p:
            a_set = set(p for p in a_p if p > 0)
            b_set = set(p for p in b_p if p > 0)
            shared = a_set & b_set
            if shared:
                return (-15, f"HALF-SIBLINGS (shared parent #{list(shared)[0]})")
        
        # 4. Grandparent-grandchild (check both up AND down the tree)
        a_anc = get_ancestors(a, cat_map, 1)
        b_anc = get_ancestors(b, cat_map, 1)
        a_desc = get_descendants(a_id, 2)
        b_desc = get_descendants(b_id, 2)
        if a_id in b_anc or b_id in a_anc or a_id in b_desc or b_id in a_desc:
            return (-15, "GRANDPARENT-GRANDCHILD")
        
        # 5. Aunt/Uncle - Niece/Nephew (shared grandparents)
        a_anc2 = get_ancestors(a, cat_map, 2)
        b_anc2 = get_ancestors(b, cat_map, 2)
        shared_anc2 = a_anc2 & b_anc2
        if shared_anc2:
            return (-10, f"AUNT/UNCLE-NEPHEW/NIECE (shared ancestor #{list(shared_anc2)[0]})")
        
        # 6. First cousins (shared great-grandparents)
        a_anc3 = get_ancestors(a, cat_map, 3)
        b_anc3 = get_ancestors(b, cat_map, 3)
        shared_anc3 = a_anc3 & b_anc3
        if shared_anc3:
            return (-5, f"COUSINS (3-gen)")
        
        return (0, "")

    def breed_score(m, f, stimulation=100):
        """Score a breeding pair based on expected offspring stats.
        
        Uses the game's inheritance formula:
        P(inherit higher) = (100 + |Stimulation|) / (200 + |Stimulation|)
        Per stat: kitten inherits one parent's value. If parents match, it's guaranteed.
        """
        m_stats = m.get('stats', {}) or {}
        f_stats = f.get('stats', {}) or {}
        m_bc = m.get('breed_code', 'unknown')
        f_bc = f.get('breed_code', 'unknown')
        m_focus = m.get('stat_focus', 'unknown')
        f_focus = f.get('stat_focus', 'unknown')
        m_cls = m.get('cat_class', 'unknown')
        f_cls = f.get('cat_class', 'unknown')

        # Inheritance probability per stat (game formula)
        p = (100 + abs(stimulation)) / (200 + abs(stimulation))
        
        reasons = []
        expected_total = 0.0
        guaranteed_7s = 0
        covered_7s = []
        
        for stat in all_stats:
            mv = m_stats.get(stat, 0)
            fv = f_stats.get(stat, 0)
            
            if mv == fv:
                expected = mv  # guaranteed inheritance
                if mv == 7:
                    guaranteed_7s += 1
            else:
                higher = max(mv, fv)
                lower = min(mv, fv)
                expected = higher * p + lower * (1 - p)
            
            expected_total += expected
            if mv == 7 or fv == 7:
                covered_7s.append(stat)
        
        covered = sorted(covered_7s)
        missing = [s for s in all_stats if s not in covered]
        
        # Expected offspring stat quality
        expected_avg = expected_total / 7
        score = expected_total  # Base score = expected stat sum (max 49)
        
        if guaranteed_7s >= 5:
            reasons.append(f"🔥 {guaranteed_7s}/7 stats guaranteed at 7!")
        elif guaranteed_7s >= 3:
            reasons.append(f"⭐ {guaranteed_7s} stats guaranteed at 7")
        elif guaranteed_7s > 0:
            reasons.append(f"{guaranteed_7s} stat(s) guaranteed at 7")
        
        if expected_total >= 46:
            reasons.append(f"🏆 Near-perfect expected: avg {expected_avg:.2f} (total {expected_total:.1f}/49)")
        elif expected_total >= 42:
            reasons.append(f"Excellent expected: avg {expected_avg:.2f} (total {expected_total:.1f}/49)")
        elif expected_total >= 35:
            reasons.append(f"Good expected: avg {expected_avg:.2f} (total {expected_total:.1f}/49) at {stimulation} Stim")
        elif expected_total >= 28:
            reasons.append(f"Decent expected: avg {expected_avg:.2f} (total {expected_total:.1f}/49)")
        
        # Stimulation note
        if guaranteed_7s < 7:
            reasons.append(f"{p:.0%} chance per stat to inherit higher ({stimulation} Stim)")
        
        # Stat-7 coverage info
        if len(covered) > 0:
            reasons.append(f"Parent 7s: {', '.join(covered)}")
        
        # --- BREED COMPATIBILITY (small bonus) ---
        if m_bc != 'unknown' and f_bc != 'unknown':
            if m_focus == f_focus:
                tw = tier_weight.get(m_bc[0], 1) + tier_weight.get(f_bc[0], 1)
                score += tw * 0.3
                reasons.append(f"Same breed focus: {m_focus}")
            else:
                score += 0.5
                reasons.append(f"Complementary focus: {m_focus} + {f_focus}")

        # --- CLASS (small bonus) ---
        if m_cls == f_cls and m_cls != 'unknown' and m_cls != 'Colorless':
            score += 1.0
            reasons.append(f"Same class: {m_cls}")
        elif m_cls != f_cls and m_cls != 'unknown' and f_cls != 'unknown':
            score += 0.3
            reasons.append(f"Hybrid: {m_cls} × {f_cls}")

        # --- ABILITIES (small bonus) ---
        m_abs = set(m.get('abilities', []))
        f_abs = set(f.get('abilities', []))
        shared = m_abs & f_abs
        unique_m = m_abs - f_abs
        unique_f = f_abs - m_abs
        score += len(shared) * 0.3
        score += len(unique_m) * 0.1
        score += len(unique_f) * 0.1

        # --- CONSANGUINITY PENALTY ---
        cat_map = {c['id']: c for c in available}
        penalty, rel = pedigree_relation(m, f, cat_map)
        if penalty < 0:
            score += penalty
            reasons.append(f"🚫 {rel} (-{abs(penalty)})")

        # --- BACKUP: mutation similarity ---
        if penalty == 0:
            ma = m.get('mutations', {}) or {}
            fb = f.get('mutations', {}) or {}
            if ma and fb:
                shared_mut = sum(1 for k, v in ma.items() if k in fb and fb[k] == v)
                total_mut = max(len(ma), len(fb))
                mut_sim = shared_mut / total_mut if total_mut > 0 else 0
                if mut_sim > 0.5:
                    score -= 6
                    reasons.append(f"🚫 High mutation similarity ({mut_sim:.0%})")
                    penalty = -6
                elif mut_sim > 0.35:
                    score -= 3
                    reasons.append(f"⚠️ Moderate mutation similarity ({mut_sim:.0%})")
                    penalty = -3

        mut_info = {
            'covered': covered,
            'missing': missing,
            'pair_stat7_count': len(covered),
            'expected_total': round(expected_total, 1),
            'kinship_penalty': penalty,
        }
        return round(score, 1), reasons, mut_info

    def kinship_severity(penalty):
        """Map penalty to severity level (0=none, 5=worst)."""
        if penalty >= 0: return 0
        if penalty <= -25: return 5
        if penalty <= -20: return 4
        if penalty <= -15: return 3
        if penalty <= -10: return 2
        return 1

    pairs = []
    # Male × Female
    for m in males:
        for f in females:
            score, reasons, meta = breed_score(m, f)
            if score >= 3:
                pairs.append({
                    'male_id': m['id'], 'male_name': m['name'],
                    'female_id': f['id'], 'female_name': f['name'],
                    'score': score, 'reasons': reasons,
                    'type': 'M/F',
                    'stat7_covered': meta['covered'],
                    'stat7_missing': meta['missing'],
                    'stat7_count': meta['pair_stat7_count'],
                    'expected_total': meta.get('expected_total', 0),
                    'kinship_penalty': meta.get('kinship_penalty', 0),
                })

    # Ditto pairs
    for d in dittos:
        for m in males:
            score, reasons, meta = breed_score(m, d)
            if score >= 3:
                pairs.append({
                    'male_id': m['id'], 'male_name': m['name'],
                    'female_id': d['id'], 'female_name': d['name'] + ' ♲',
                    'score': score, 'reasons': reasons,
                    'type': 'M/D',
                    'stat7_covered': meta['covered'],
                    'stat7_missing': meta['missing'],
                    'stat7_count': meta['pair_stat7_count'],
                    'expected_total': meta.get('expected_total', 0),
                    'kinship_penalty': meta.get('kinship_penalty', 0),
                })
    for d in dittos:
        for f in females:
            score, reasons, meta = breed_score(d, f)
            if score >= 3:
                pairs.append({
                    'male_id': d['id'], 'male_name': d['name'] + ' ♲',
                    'female_id': f['id'], 'female_name': f['name'],
                    'score': score, 'reasons': reasons,
                    'type': 'D/F',
                    'stat7_covered': meta['covered'],
                    'stat7_missing': meta['missing'],
                    'stat7_count': meta['pair_stat7_count'],
                    'expected_total': meta.get('expected_total', 0),
                    'kinship_penalty': meta.get('kinship_penalty', 0),
                })

    # Sort: non-consanguineous first, then by score (expected stat total) descending
    pairs.sort(key=lambda x: (
        kinship_severity(x.get('kinship_penalty', 0)),
        x.get('kinship_penalty', 0),
        -x['score'],
    ))
    insights['compatible_pairs'] = pairs  # No limit - all pairs computed
    return insights


def generate_standalone_html(cats_json, insights_json):
    """Generate a self-contained HTML file with embedded JSON data."""
    template_path = os.path.join(os.path.dirname(__file__), 'app.html')
    
    with open(template_path, 'r', encoding='utf-8') as f:
        html = f.read()
    
    # Embed the JSON data directly as JavaScript variables
    # Replace the fetch() calls with inline data
    embedded_script = f'''<script>
// EMBEDDED DATA - Generated by extract_data.py
const EMBEDDED_CATS_DATA = {cats_json};
const EMBEDDED_INSIGHTS_DATA = {insights_json};
</script>'''
    
    # Insert RIGHT AFTER the opening <body> tag so it loads BEFORE any other script
    html = html.replace('<body>', '<body>\n' + embedded_script)
    
    # Replace the loadData function to use embedded data
    old_load = '''async function loadData() {
  try {
    const [catsRes, insightsRes] = await Promise.all([
      fetch('cats_data.json'),
      fetch('breeding_insights.json')
    ]);
    catsData = await catsRes.json();
    insightsData = await insightsRes.json();
    
    document.getElementById('catCount').innerHTML = `<strong>${catsData.length}</strong> gatos carregados`;
    populateFilters();
    renderAll();
  } catch (e) {
    console.error('Error loading data:', e);
    document.getElementById('catCount').textContent = 'Erro ao carregar dados';
    document.getElementById('catsTableBody').innerHTML = 
      '<tr><td colspan="6" style="text-align:center;padding:48px;color:var(--warn)">⚠️ Erro ao carregar cats_data.json. Execute extract_data.py primeiro.</td></tr>';
  }
}'''
    
    new_load = '''async function loadData() {
  // Try embedded data first (standalone mode), fall back to fetch
  if (typeof EMBEDDED_CATS_DATA !== 'undefined' && typeof EMBEDDED_INSIGHTS_DATA !== 'undefined') {
    catsData = EMBEDDED_CATS_DATA;
    insightsData = EMBEDDED_INSIGHTS_DATA;
    document.getElementById('catCount').innerHTML = `<strong>${catsData.length}</strong> gatos carregados`;
    populateFilters();
    renderAll();
    return;
  }
  
  try {
    const [catsRes, insightsRes] = await Promise.all([
      fetch('cats_data.json'),
      fetch('breeding_insights.json')
    ]);
    catsData = await catsRes.json();
    insightsData = await insightsRes.json();
    
    document.getElementById('catCount').innerHTML = `<strong>${catsData.length}</strong> gatos carregados`;
    populateFilters();
    renderAll();
  } catch (e) {
    console.error('Error loading data:', e);
    document.getElementById('catCount').textContent = 'Erro ao carregar dados';
    document.getElementById('catsTableBody').innerHTML = 
      '<tr><td colspan="6" style="text-align:center;padding:48px;color:var(--warn)">⚠️ Erro ao carregar cats_data.json. Execute extract_data.py primeiro.</td></tr>';
  }
}'''
    
    html = html.replace(old_load, new_load)
    
    output_path = os.path.join(os.path.dirname(__file__), 'app_standalone.html')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"Standalone HTML saved to: {output_path}")
    return output_path


def main():
    save_path = REAL_SAVE_PATH
    output_path = os.path.join(os.path.dirname(__file__), 'cats_data.json')
    insights_path = os.path.join(os.path.dirname(__file__), 'breeding_insights.json')

    print(f"Reading save file: {save_path}")
    cats = extract_all_cats(save_path)

    print(f"Extracted {len(cats)} cats")
    print(f"Saving to: {output_path}")
    cats_json_str = json.dumps(cats, indent=2, ensure_ascii=False)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(cats_json_str)

    print("Generating breeding insights...")
    insights = build_breeding_insights(cats)

    print(f"Saving insights to: {insights_path}")
    insights_json_str = json.dumps(insights, indent=2, ensure_ascii=False)
    with open(insights_path, 'w', encoding='utf-8') as f:
        f.write(insights_json_str)

    # Generate standalone HTML (no fetch needed - works from file://)
    generate_standalone_html(cats_json_str, insights_json_str)

    # Print summary
    alive_active = [c for c in cats if c.get('is_active') and not c.get('is_dead')]
    dead_active = [c for c in cats if c.get('is_active') and c.get('is_dead')]
    available = [c for c in cats if c.get('available')]
    print(f"\n=== SUMMARY ===")
    print(f"Total cats in DB: {insights['total_cats']}")
    print(f"Active cats (house+adventure): {len(alive_active) + len(dead_active)}")
    print(f"  Alive: {len(alive_active)} | Dead: {len(dead_active)}")
    print(f"  Retired (alive): {sum(1 for c in alive_active if c.get('is_retired'))}")
    print(f"Available for breeding: {insights['available_cats']}")
    print(f"Gender: {insights['gender_distribution']}")
    print(f"Classes: {insights['class_distribution']}")

    # Stat-7 highlights
    s7 = insights.get('stat7_summary', [])
    if s7:
        print(f"\nStat-7 Leaders (cats with most 7s):")
        for c in s7[:5]:
            active_tag = "🏠" if c.get('is_active') else ""
            print(f"  {active_tag} {c['name']}: {c['stat7_count']} seven(s) = {c['stat7_list']} (total {c['stat_total']})")
        total_at7 = sum(1 for c in cats if c.get('stat7_count', 0) > 0)
        print(f"Total cats with at least one stat-7: {total_at7}")
    print(f"Top breeds: {dict(sorted(insights['breed_distribution'].items(), key=lambda x: -x[1])[:10])}")
    print(f"Top 5 compatible pairs:")
    for pair in insights['compatible_pairs'][:5]:
        print(f"  ♂ {pair['male_name']} × ♀ {pair['female_name']} (score: {pair['score']})")
        for r in pair['reasons']:
            print(f"    - {r}")

    print("\nDone! Open src/app_standalone.html in your browser.")


if __name__ == '__main__':
    main()

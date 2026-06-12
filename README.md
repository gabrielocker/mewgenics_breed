# Mewgenics Breeding Tool

<p align="center">
  <a href="https://github.com/gabrielocker/mewgenics_breed/releases/download/alpha/MewgenicsBreeding.exe">
    <img src="https://img.shields.io/badge/⬇%20Baixar%20MewgenicsBreeding.exe%20⬇-008000?style=for-the-badge&logo=windows&logoColor=white" alt="Download">
  </a>
  <br>
  <sub>~15 MB • Windows 10/11 • WebView2 incluso no sistema</sub>
</p>

Desktop app for analyzing cat genetics and breeding pairs from *Mewgenics* save files. Extracts cat data directly from `.sav` file, reconstructs family trees from the pedigree table, and scores all viable breeding pairs using the game's current stats.

## How it works

1. **Reads** the Mewgenics save file (`steamcampaign01.sav`) in read-only mode and never modifies your game data.
2. **Decompresses** decompresses the .sav file.
3. **Parses** credits to TeaFull6669 (used his parser after failing to extract data from .sav file).
4. **Rebuilds genealogy** from the `pedigree` table, identifies parents, children and consanguinity.
5. **Scores breeding pairs** with the game's inheritance formula (https://mewgenics.wiki.gg).
6. **Detects consanguinity** — flags incestuous pairs with severity ratings and score penalties.

## Breeding formula

The game inherits stats per gene with this probability:

$$P(\text{inherit higher}) = \frac{100 + |\text{Stim}|}{200 + |\text{Stim}|}$$

At default 100 Stim, a kitten has ~66.7% chance to inherit the higher parent value for each stat. The app calculates expected value per stat and sums them into a score out of 49 (7 stats × max 7).

**Pair quality tiers:**

| Expected total | Label         |
| -------------- | ------------- |
| >= 46          | Near-perfect  |
| >= 42          | Excellent     |
| >= 35          | Good          |
| >= 28          | Decent         |

## Consanguinity detection

Family relationships are mapped up to 3 generations:

| Relationship        | Penalty |
| ------------------- | ------- |
| Parent-Child        | -25     |
| Full Siblings       | -20     |
| Half-Siblings       | -15     |
| Grandparent         | -15     |
| Aunt/Uncle          | -10     |
| Cousins (3-gen)     | -5      |

Pairs are sorted: clean pairs first, then consanguineous by severity, then by score.

## Features

- **All Cats tab** — sortable table with filters (status, class, gender, breed focus). Click any cat for a detailed modal with stats, abilities, mutations, and items.
- **Breeding tab** — full list of compatible pairs with expected offspring stats, breed synergy, and consanguinity warnings. Collapsible sections for clean vs flagged pairs. Block pairs you're not interested in.
- **Stats tab** — distribution charts for genders, classes, breeds, stat focuses, and ability frequency.

## Project structure

```
mewgenics_breeding/
  src/
    extract_data.py    # Core engine: SQLite read, LZ4 decompress, binary parse, breeding logic
    app.py             # PyWebView desktop entry point
    app.html           # Complete UI
    img/icons/         # SVG stat icons
  dist/
    MewgenicsBreeding.exe   # Standalone .exe (PyInstaller onefile, ~15MB)
  save/
    steamcampaign01.sav      # Sample save (for development reference)
```

## Building

```powershell
# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install pywebview pyinstaller (or pip install -r requirements.txt)

# Build standalone .exe
python -m PyInstaller --onefile --windowed --name "MewgenicsBreeding" `
  --add-data "src\app.html;." `
  --add-data "src\extract_data.py;." `
  --add-data "src\img\icons\*.svg;img\icons" `
  --hidden-import webview.platforms.winforms `
  --hidden-import clr `
  --collect-all webview `
  --distpath dist `
  src\app.py
```

The `.exe` requires **WebView2 Runtime** (pre-installed on Windows 10/11).

## Running from source

```powershell
.\.venv\Scripts\Activate.ps1
python src\app.py
```

Or to extract data and generate a standalone HTML report:

```powershell
python src\extract_data.py
```

## Tech stack

- **Python 3.13** — core logic
- **PyWebView** — native desktop window via WebView2
- **PyInstaller** — onefile .exe packaging
- **SQLite3** — save file access
- **Vanilla HTML/CSS/JS** — dark-themed UI, no frameworks

# Kapteins Loggbok

Generates a coherent captain's logbook in Norwegian, inspired by historical ship logs from 1500–1800. Each entry is written by a fictional captain sailing random coordinates within a configured geographical bounding box, using real weather data from Met.no.

## How it works

1. Picks a random position within the bounding box in `config.toml`
2. Fetches real weather from [Met.no](https://api.met.no/)
3. Reads the last N entries from `logbook.md` as narrative context
4. Generates a new entry via Ollama that continues the story
5. Prepends the entry to `logbook.md` (newest at top)

## Setup

```bash
uv run main.py
```

Or with pip:

```bash
pip install requests ollama
python main.py
```

## Configuration

Edit `config.toml`:

```toml
[captain]
name = "Kaptein Salveson"
ship = "M/S Frierholmen"

[bbox]
lon_min = 9.013939
lat_min = 58.587672
lon_max = 9.151268
lat_max = 58.634880

[logbook]
path = "logbook.md"
past_entries_count = 3

[model]
name = "gemma4:31b-cloud"
```

## Usage

```bash
# Write to logbook (default)
uv run main.py

# Preview in shell without writing
uv run main.py --output shell

# Use a different model
uv run main.py --model llama3.2

# Use a different config file
uv run main.py --config my-config.toml
```

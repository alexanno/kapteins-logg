#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "requests>=2.31.0",
#   "ollama>=0.1.0",
# ]
# ///
"""
Kapteins Loggbok — generates coherent ship log entries in Norwegian.

Each run:
1. Picks a random position within the configured bounding box
2. Fetches real weather data from Met.no for that position
3. Reads the last N entries from the single logbook file for narrative context
4. Generates a new entry via Ollama, continuing the story
5. Prepends the new entry to the logbook (newest at top)
"""

import random
import sys
import tomllib
import argparse
from datetime import datetime
from pathlib import Path
import requests
import ollama


WEATHER_SYMBOL_LABELS = {
    "clearsky": "klar himmel",
    "fair": "lettskyet",
    "partlycloudy": "delvis skyet",
    "cloudy": "skyet",
    "fog": "tåke",
    "lightrain": "lett regn",
    "rain": "regn",
    "heavyrain": "kraftig regn",
    "lightsleet": "lett sludd",
    "sleet": "sludd",
    "heavysleet": "kraftig sludd",
    "lightsnow": "lett snø",
    "snow": "snø",
    "heavysnow": "kraftig snø",
    "rainshowers": "regnbyger",
    "heavyrainshowers": "kraftige regnbyger",
    "lightrainshowers": "lette regnbyger",
    "lightsleetshowers": "lette sluddbyger",
    "sleetshowers": "sluddbyger",
    "heavysleetshowers": "kraftige sluddbyger",
    "lightsnowshowers": "lette snøbyger",
    "snowshowers": "snøbyger",
    "heavysnowshowers": "kraftige snøbyger",
}


def load_config(path: str = "config.toml") -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def random_position_in_bbox(bbox: dict) -> tuple[float, float]:
    """Return a random (lat, lon) within the configured bounding box."""
    lat = random.uniform(bbox["lat_min"], bbox["lat_max"])
    lon = random.uniform(bbox["lon_min"], bbox["lon_max"])
    return round(lat, 4), round(lon, 4)


def fetch_weather(lat: float, lon: float) -> dict:
    url = (
        "https://api.met.no/weatherapi/locationforecast/2.0/complete"
        f"?lat={lat}&lon={lon}"
    )
    headers = {"User-Agent": "kapteins-logg (github.com/alexandesn/kapteins-logg)"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        series = r.json().get("properties", {}).get("timeseries", [])
        return series[0] if series else {}
    except Exception as e:
        print(f"Advarsel: Kunne ikke henteværdata: {e}", file=sys.stderr)
        return {}


def format_wind_direction(degrees: float) -> str:
    dirs = ["N", "NNO", "NO", "ONO", "O", "OSO", "SO", "SSO",
            "S", "SSV", "SV", "VSV", "V", "VNV", "NV", "NNV"]
    return dirs[int((degrees + 11.25) // 22.5) % len(dirs)]


def format_symbol(code: str) -> str:
    base = code.split("_")[0] if code else ""
    return WEATHER_SYMBOL_LABELS.get(base, base.replace("_", " "))


def format_forecast_period(label: str, block: dict) -> str:
    if not block:
        return ""
    parts = []
    summary = block.get("summary", {})
    details = block.get("details", {})
    if summary.get("symbol_code"):
        parts.append(f"vær {format_symbol(summary['symbol_code'])}")
    if "precipitation_amount" in details:
        parts.append(f"nedbør {details['precipitation_amount']} mm")
    if "probability_of_precipitation" in details:
        parts.append(f"nedbørssjanse {details['probability_of_precipitation']} %")
    if "air_temperature_min" in details and "air_temperature_max" in details:
        parts.append(f"temperatur {details['air_temperature_min']}–{details['air_temperature_max']} °C")
    return f"- {label}: " + ", ".join(parts) if parts else ""


def format_weather(weather: dict) -> str:
    if not weather:
        return "Ingen værdata tilgjengelig"

    data = weather.get("data", {})
    instant = data.get("instant", {}).get("details", {})
    lines = []

    if weather.get("time"):
        lines.append(f"- Observasjonstid: {weather['time']}")

    now_parts = []
    if "air_temperature" in instant:
        now_parts.append(f"temperatur {instant['air_temperature']} °C")
    if "air_pressure_at_sea_level" in instant:
        now_parts.append(f"lufttrykk {instant['air_pressure_at_sea_level']} hPa")
    if "relative_humidity" in instant:
        now_parts.append(f"luftfuktighet {instant['relative_humidity']} %")
    if now_parts:
        lines.append("- Nå: " + ", ".join(now_parts))

    wind_parts = []
    if "wind_speed" in instant:
        wind_parts.append(f"vind {instant['wind_speed']} m/s")
    if "wind_speed_of_gust" in instant:
        wind_parts.append(f"kast {instant['wind_speed_of_gust']} m/s")
    if "wind_from_direction" in instant:
        d = instant["wind_from_direction"]
        wind_parts.append(f"fra {format_wind_direction(d)} ({d}°)")
    if wind_parts:
        lines.append("- Vind: " + ", ".join(wind_parts))

    sky_parts = []
    if "cloud_area_fraction" in instant:
        sky_parts.append(f"skydekke {instant['cloud_area_fraction']} %")
    if "fog_area_fraction" in instant:
        sky_parts.append(f"tåkeandel {instant['fog_area_fraction']} %")
    if sky_parts:
        lines.append("- Sikt/skydekke: " + ", ".join(sky_parts))

    for label, key in [
        ("Neste time", "next_1_hours"),
        ("Neste 6 timer", "next_6_hours"),
        ("Neste 12 timer", "next_12_hours"),
    ]:
        line = format_forecast_period(label, data.get(key, {}))
        if line:
            lines.append(line)

    return "\n".join(lines) if lines else "Ingen spesifikke værdetaljer"


def read_past_entries(logbook_path: Path, n: int) -> list[str]:
    """
    Parse the last N entries from the logbook file.
    Entries are separated by lines containing only '---'.
    Newest entry is first in the file (after the header block).
    """
    if not logbook_path.exists():
        return []

    text = logbook_path.read_text(encoding="utf-8")
    # Split on entry dividers
    parts = [p.strip() for p in text.split("\n---\n")]
    # Filter to actual entries (they start with '##')
    entries = [p for p in parts if p.startswith("##")]
    return entries[:n]


def build_system_prompt(captain_name: str, ship_name: str) -> str:
    return f"""Du er {captain_name}, kaptein på skipet {ship_name} som seiler langs norskekysten i perioden 1500–1800.
Din oppgave er å skrive autentiske skipsdagbokoppføringer på norsk som:
- Er skrevet i stil fra gamle norske og engelske skipsdagbøker
- Er geografisk og meteorologisk rimelig nøyaktige
- Bygger videre på tidligere oppføringer når de er tilgjengelige (referer til vær, hendelser, mannskap, kurs)
- Er kreative men troverdige — som fra en virkelig kaptein
- Gjerne inneholder korte vers, naturobservasjoner eller beretninger fra mannskapet
- Signeres alltid med kapteinens navn

Eksempler på stilmåte:

9th Monday. First part commences with moderate breezy. Tack ship she knock off. Middle part tack ship. Latter part furled top gallants. So ends with a stiff breeze. Latt 19=56

Oktober 12: Vakkert vær. Lett bris. Styrende SE ved Ø. Natt: Kastet jardene. Kurs SW. Endret kurs da vi befant oss ved kysten av Barbaria.

Oktober 14: Vannet er igjen farget dypgrønt. Mellom 3-4 ettermiddag så vi en stor pottfisk. Senket ned 3 båter. Sjøen går høyt. Satte all seil igjen. Vær: Skyet.
"""


def generate_entry(
    lat: float,
    lon: float,
    weather_desc: str,
    past_entries: list[str],
    config: dict,
    model: str,
) -> str:
    captain = config["captain"]["name"]
    ship = config["captain"]["ship"]

    context_block = ""
    if past_entries:
        joined = "\n\n---\n\n".join(past_entries)
        context_block = f"""TIDLIGERE LOGGOPPFØRINGER (bruk disse som kontekst og fortsett fortellingen):

{joined}

"""

    prompt = f"""{context_block}DAGENS POSISJON:
- Koordinater: {lat}°N, {lon}°Ø
- Skip: {ship}

VÆRDATA:
{weather_desc}

Skriv neste dagbokoppføring (4–15 linjer). Bruk værdataene konkret. Bygg videre på tidligere oppføringer der det er naturlig. Skriv KUN selve dagbokoppføringen — ikke metadata, ikke overskrift.
"""

    try:
        response = ollama.generate(
            model=model,
            prompt=prompt,
            system=build_system_prompt(captain, ship),
            stream=False,
        )
        return response.get("response", "").strip()
    except Exception as e:
        print(f"Feil ved generering: {e}", file=sys.stderr)
        return ""


_MONTHS_NO = [
    "", "januar", "februar", "mars", "april", "mai", "juni",
    "juli", "august", "september", "oktober", "november", "desember",
]


def format_entry_header(lat: float, lon: float) -> str:
    now = datetime.now()
    month = _MONTHS_NO[now.month]
    date_str = f"{now.day}. {month} {now.year}, {now.strftime('%H:%M')}"
    return f"## {date_str} | {lat}°N, {lon}°Ø"


def prepend_to_logbook(logbook_path: Path, entry_text: str, header: str) -> None:
    """Insert new entry at the top of the logbook, after the title block."""
    new_block = f"{header}\n\n{entry_text}"

    if not logbook_path.exists():
        title = "# Kapteins Loggbok\n"
        logbook_path.write_text(
            f"{title}\n---\n\n{new_block}\n",
            encoding="utf-8",
        )
        return

    existing = logbook_path.read_text(encoding="utf-8")

    # Find where the first entry starts (after the title block and first ---)
    divider = "\n---\n"
    idx = existing.find(divider)
    if idx == -1:
        # No entries yet — just append
        logbook_path.write_text(
            existing.rstrip() + f"\n\n---\n\n{new_block}\n",
            encoding="utf-8",
        )
    else:
        before = existing[: idx + len(divider)]
        after = existing[idx + len(divider):]
        logbook_path.write_text(
            before + f"\n{new_block}\n\n---\n\n" + after.lstrip(),
            encoding="utf-8",
        )


def main():
    parser = argparse.ArgumentParser(description="Generer ny kapteinslogg-oppføring")
    parser.add_argument("--config", default="config.toml", help="Konfigurasjonsfil")
    parser.add_argument("--model", help="Overstyr Ollama-modell fra config")
    parser.add_argument(
        "--output",
        choices=["logbook", "shell"],
        default="logbook",
        help="Utdata: legg til i loggboken (standard) eller skriv til shell",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    model = args.model or config["model"]["name"]
    logbook_path = Path(config["logbook"]["path"])
    past_n = config["logbook"]["past_entries_count"]

    lat, lon = random_position_in_bbox(config["bbox"])
    weather = fetch_weather(lat, lon)
    weather_desc = format_weather(weather)
    past_entries = read_past_entries(logbook_path, past_n)

    print(f"📍 Posisjon: {lat}°N, {lon}°Ø", file=sys.stderr)
    print(f"🌦️  Henter vær og {len(past_entries)} tidligere oppføringer...", file=sys.stderr)

    entry_text = generate_entry(lat, lon, weather_desc, past_entries, config, model)

    if not entry_text:
        print("Feil: Klarte ikke generere oppføring", file=sys.stderr)
        sys.exit(1)

    header = format_entry_header(lat, lon)

    if args.output == "shell":
        print(f"\n{header}\n\n{entry_text}\n")
    else:
        prepend_to_logbook(logbook_path, entry_text, header)
        print(f"✅ Lagt til i {logbook_path}", file=sys.stderr)


if __name__ == "__main__":
    main()

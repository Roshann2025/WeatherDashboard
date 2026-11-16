"""Weather Dashboard: Tkinter desktop app fetching Open-Meteo forecasts in a dark UI."""
import datetime, json, os, threading, tkinter as tk
from tkinter import messagebox, ttk

try:
    import requests
except ImportError:
    requests = None
    import urllib.error, urllib.parse, urllib.request

# WMO Weather Codes: code -> (readable_text, emoji)
WMO_CODES = {
    0: ("Clear Sky", "☀️"), 1: ("Mainly Clear", "🌤️"), 2: ("Partly Cloudy", "⛅"), 3: ("Overcast", "☁️"),
    45: ("Foggy", "🌫️"), 48: ("Rime Fog", "🌫️"), 51: ("Light Drizzle", "🌦️"), 53: ("Drizzle", "🌧️"),
    55: ("Dense Drizzle", "🌧️"), 56: ("Freezing Drizzle", "🌨️"), 57: ("Dense Frz Drizzle", "🌨️"),
    61: ("Slight Rain", "🌧️"), 63: ("Moderate Rain", "🌧️"), 65: ("Heavy Rain", "🌧️"),
    66: ("Freezing Rain", "🌨️"), 67: ("Heavy Frz Rain", "🌨️"), 71: ("Slight Snow", "🌨️"),
    73: ("Moderate Snow", "❄️"), 75: ("Heavy Snow", "❄️"), 77: ("Snow Grains", "❄️"),
    80: ("Light Showers", "🌦️"), 81: ("Showers", "🌧️"), 82: ("Violent Showers", "⛈️"),
    85: ("Snow Showers", "🌨️"), 86: ("Heavy Snow Shwrs", "❄️"), 95: ("Thunderstorm", "⛈️"),
    96: ("Thunderstorm w/ Hail", "⛈️"), 99: ("Severe Storm", "⛈️"),
}


def get_weather_condition(code: int) -> tuple[str, str]:
    """Return condition text and matching emoji for a given WMO code."""
    return WMO_CODES.get(code, ("Unknown", "🌡️"))


class WeatherApp:
    """Class-based Weather Dashboard desktop application."""

    GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
    CONFIG_FILE = "weather_config.json"
    BG_ROOT, BG_CARD, BORDER = "#181a20", "#22252d", "#2f333f"
    TEXT_PRI, TEXT_SEC, ACCENT = "#ffffff", "#9aa0a6", "#2563eb"

    def __init__(self, root: tk.Tk) -> None:
        """Initialize main window, styles, layout, and load remembered city."""
        self.root = root
        self.root.title("Weather Dashboard")
        self.root.geometry("600x470")
        self.root.resizable(False, False)
        self.root.configure(bg=self.BG_ROOT)

        self.unit, self.current_city, self.weather_data, self.is_fetching = "C", "", None, False
        self.config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), self.CONFIG_FILE)

        self._init_styles()
        self._build_ui()

        saved_city, saved_unit = self._load_config()
        self.unit = saved_unit
        self._update_unit_btn()
        initial_city = saved_city or "London"
        self.search_entry.insert(0, initial_city)
        self.root.after(100, lambda: self.search_city(initial_city))

    def _init_styles(self) -> None:
        """Configure ttk styles for dark theme widgets."""
        s = ttk.Style()
        if "clam" in s.theme_names():
            s.theme_use("clam")
        s.configure("Main.TFrame", background=self.BG_ROOT)
        s.configure("Search.TEntry", fieldbackground=self.BG_CARD, foreground=self.TEXT_PRI, insertcolor=self.TEXT_PRI, bordercolor=self.BORDER, padding=5)
        s.configure("Primary.TButton", background=self.ACCENT, foreground=self.TEXT_PRI, font=("Segoe UI", 9, "bold"), bordercolor=self.ACCENT, padding=(10, 4))
        s.map("Primary.TButton", background=[("active", "#1d4ed8"), ("disabled", "#374151")])
        s.configure("Secondary.TButton", background="#333742", foreground=self.TEXT_PRI, font=("Segoe UI", 9), bordercolor=self.BORDER, padding=(8, 4))
        s.map("Secondary.TButton", background=[("active", "#3e4350"), ("disabled", "#242831")])

    def _build_ui(self) -> None:
        """Construct top bar, status row, current card, and 5-day forecast cards."""
        box = ttk.Frame(self.root, style="Main.TFrame", padding="14 12 14 12")
        box.pack(fill=tk.BOTH, expand=True)

        # 1. Top bar
        top = ttk.Frame(box, style="Main.TFrame"); top.pack(fill=tk.X, pady=(0, 6))
        self.search_entry = ttk.Entry(top, style="Search.TEntry", font=("Segoe UI", 10))
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.search_entry.bind("<Return>", lambda _: self.search_city())
        self.search_btn = ttk.Button(top, text="Search", style="Primary.TButton", command=self.search_city); self.search_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.refresh_btn = ttk.Button(top, text="Refresh", style="Secondary.TButton", command=self.refresh_weather); self.refresh_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.unit_btn = ttk.Button(top, text="Switch to °F", style="Secondary.TButton", command=self.toggle_unit); self.unit_btn.pack(side=tk.LEFT)

        # 2. Status bar
        sb = ttk.Frame(box, style="Main.TFrame"); sb.pack(fill=tk.X, pady=(0, 8))
        self.status_lbl = tk.Label(sb, text="Ready", font=("Segoe UI", 8), fg=self.TEXT_SEC, bg=self.BG_ROOT); self.status_lbl.pack(side=tk.LEFT)
        self.updated_lbl = tk.Label(sb, text="Last updated: --", font=("Segoe UI", 8), fg=self.TEXT_SEC, bg=self.BG_ROOT); self.updated_lbl.pack(side=tk.RIGHT)

        # 3. Current Weather Card
        card = tk.Frame(box, bg=self.BG_CARD, highlightbackground=self.BORDER, highlightthickness=1, padx=16, pady=12); card.pack(fill=tk.X, pady=(0, 10))
        self.location_lbl = tk.Label(card, text="Loading...", font=("Segoe UI", 16, "bold"), fg=self.TEXT_PRI, bg=self.BG_CARD, anchor="w"); self.location_lbl.pack(fill=tk.X)

        mid = tk.Frame(card, bg=self.BG_CARD); mid.pack(fill=tk.X, pady=(4, 6))
        self.temp_lbl = tk.Label(mid, text="--°C", font=("Segoe UI", 34, "bold"), fg=self.TEXT_PRI, bg=self.BG_CARD); self.temp_lbl.pack(side=tk.LEFT)
        self.condition_lbl = tk.Label(mid, text="--", font=("Segoe UI", 14), fg=self.TEXT_PRI, bg=self.BG_CARD); self.condition_lbl.pack(side=tk.LEFT, padx=(16, 0))

        metrics = tk.Frame(card, bg=self.BG_CARD); metrics.pack(fill=tk.X, pady=(2, 0))
        self.humidity_lbl = tk.Label(metrics, text="💧 Humidity: --%", font=("Segoe UI", 10), fg=self.TEXT_SEC, bg=self.BG_CARD); self.humidity_lbl.pack(side=tk.LEFT, padx=(0, 24))
        self.wind_lbl = tk.Label(metrics, text="💨 Wind: -- km/h", font=("Segoe UI", 10), fg=self.TEXT_SEC, bg=self.BG_CARD); self.wind_lbl.pack(side=tk.LEFT)

        # 4. 5-Day Forecast Row
        tk.Label(box, text="5-DAY FORECAST", font=("Segoe UI", 9, "bold"), fg=self.TEXT_SEC, bg=self.BG_ROOT, anchor="w").pack(fill=tk.X, pady=(0, 6))
        f_row = tk.Frame(box, bg=self.BG_ROOT); f_row.pack(fill=tk.BOTH, expand=True)

        self.forecast_cards: list[dict[str, tk.Widget]] = []
        for i in range(5):
            cf = tk.Frame(f_row, bg=self.BG_CARD, highlightbackground=self.BORDER, highlightthickness=1, padx=6, pady=8)
            cf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0 if i == 0 else 4, 0))
            d = tk.Label(cf, text="--", font=("Segoe UI", 10, "bold"), fg=self.TEXT_PRI, bg=self.BG_CARD); d.pack(pady=(0, 2))
            dt = tk.Label(cf, text="--/--", font=("Segoe UI", 8), fg=self.TEXT_SEC, bg=self.BG_CARD); dt.pack(pady=(0, 4))
            em = tk.Label(cf, text="--", font=("Segoe UI Emoji", 20), fg=self.TEXT_PRI, bg=self.BG_CARD); em.pack(pady=(0, 2))
            cd = tk.Label(cf, text="--", font=("Segoe UI", 8), fg=self.TEXT_SEC, bg=self.BG_CARD, wraplength=95, justify="center"); cd.pack(pady=(0, 4))
            tr = tk.Label(cf, text="-- / --", font=("Segoe UI", 9, "bold"), fg=self.TEXT_PRI, bg=self.BG_CARD); tr.pack()
            self.forecast_cards.append({"day": d, "date": dt, "emoji": em, "cond": cd, "temp_range": tr})

    # Unit Conversion & Helpers
    def _to_f(self, c: float) -> float:
        return (c * 9.0 / 5.0) + 32.0

    def _fmt_temp(self, c: float) -> str:
        return f"{round(self._to_f(c) if self.unit == 'F' else c)}°{self.unit}"

    def _fmt_num(self, c: float) -> str:
        return f"{round(self._to_f(c) if self.unit == 'F' else c)}°"

    def _fmt_wind(self, kmh: float) -> str:
        return f"{kmh * 0.621371:.1f} mph" if self.unit == "F" else f"{kmh:.1f} km/h"

    def _update_unit_btn(self) -> None:
        self.unit_btn.config(text=f"Switch to {'°F' if self.unit == 'C' else '°C'}")

    def toggle_unit(self) -> None:
        """Toggle between °C and °F and refresh display immediately."""
        self.unit = "F" if self.unit == "C" else "C"
        self._update_unit_btn()
        self._save_config(self.current_city)
        if self.weather_data:
            self._render_weather(self.weather_data)

    # Persistence
    def _load_config(self) -> tuple[str, str]:
        """Load last city and unit from JSON file."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    return d.get("last_city", "").strip(), d.get("unit", "C")
            except (json.JSONDecodeError, OSError):
                pass
        return "", "C"

    def _save_config(self, city: str) -> None:
        """Save current city and unit to JSON file."""
        if city:
            try:
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump({"last_city": city, "unit": self.unit}, f, indent=2)
            except OSError:
                pass

    # Threaded API Operations
    def search_city(self, city_name: str | None = None) -> None:
        """Initiate non-blocking weather search."""
        if self.is_fetching:
            return
        query = city_name if city_name is not None else self.search_entry.get().strip()
        if not query:
            messagebox.showwarning("Input Required", "Please enter a city name.", parent=self.root)
            return

        self.is_fetching = True
        self.search_btn.config(state=tk.DISABLED)
        self.refresh_btn.config(state=tk.DISABLED)
        self.status_lbl.config(text=f"Searching for '{query}'...")
        threading.Thread(target=self._fetch_worker, args=(query,), daemon=True).start()

    def refresh_weather(self) -> None:
        """Refresh current city's weather data."""
        city = self.current_city or self.search_entry.get().strip()
        if city:
            self.search_city(city)

    def _fetch_json(self, url: str, params: dict) -> dict:
        """Fetch JSON using requests or standard urllib fallback."""
        if requests is not None:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        qs = urllib.parse.urlencode(params)
        req = urllib.request.Request(f"{url}?{qs}", headers={"User-Agent": "WeatherApp/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _fetch_worker(self, query: str) -> None:
        """Worker thread executing Geocoding and Forecast API requests."""
        try:
            geo = self._fetch_json(self.GEO_URL, {"name": query, "count": 1, "language": "en", "format": "json"})
            results = geo.get("results")
            if not results:
                self.root.after(0, self._on_error, "City Not Found", f"Could not find '{query}'. Check spelling.")
                return

            loc = results[0]
            lat, lon = loc["latitude"], loc["longitude"]
            city, country = loc.get("name", query), loc.get("country", loc.get("country_code", ""))

            f_params = {
                "latitude": lat, "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                "timezone": "auto", "forecast_days": 6,
            }
            fc = self._fetch_json(self.FORECAST_URL, f_params)
            cur, daily = fc.get("current"), fc.get("daily")
            if not cur or not daily:
                self.root.after(0, self._on_error, "API Failure", "Incomplete weather data received.")
                return

            self.root.after(0, self._on_success, {"city": city, "country": country, "current": cur, "daily": daily})

        except Exception as exc:
            msg, err_type = str(exc), "API Failure"
            if (requests and isinstance(exc, requests.exceptions.ConnectionError)) or hasattr(exc, "reason"):
                err_type, msg = "No Internet Connection", "Unable to connect. Check your network."
            elif (requests and isinstance(exc, requests.exceptions.Timeout)) or isinstance(exc, TimeoutError):
                err_type, msg = "Request Timeout", "Server took too long to respond. Try again."
            self.root.after(0, self._on_error, err_type, msg)

    # UI Update Handlers
    def _on_success(self, payload: dict) -> None:
        """Process API response and update UI on main thread."""
        self.is_fetching = False
        self.search_btn.config(state=tk.NORMAL)
        self.refresh_btn.config(state=tk.NORMAL)
        self.current_city, self.weather_data = payload["city"], payload

        self.search_entry.delete(0, tk.END)
        self.search_entry.insert(0, self.current_city)
        self._render_weather(payload)
        self.updated_lbl.config(text=f"Last updated: {datetime.datetime.now().strftime('%H:%M:%S')}")
        self.status_lbl.config(text="Weather updated successfully.")
        self._save_config(self.current_city)

    def _on_error(self, title: str, message: str) -> None:
        """Display error dialog on main thread."""
        self.is_fetching = False
        self.search_btn.config(state=tk.NORMAL)
        self.refresh_btn.config(state=tk.NORMAL)
        self.status_lbl.config(text="Error updating weather.")
        messagebox.showerror(title, message, parent=self.root)

    def _render_weather(self, data: dict) -> None:
        """Render current weather and 5-day forecast cards."""
        loc = f"{data['city']}, {data['country']}" if data.get("country") else data["city"]
        self.location_lbl.config(text=loc)

        cur = data["current"]
        cond, emoji = get_weather_condition(cur.get("weather_code", -1))
        self.temp_lbl.config(text=self._fmt_temp(cur.get("temperature_2m", 0.0)))
        self.condition_lbl.config(text=f"{emoji}  {cond}")
        self.humidity_lbl.config(text=f"💧 Humidity: {cur.get('relative_humidity_2m', 0)}%")
        self.wind_lbl.config(text=f"💨 Wind: {self._fmt_wind(cur.get('wind_speed_10m', 0.0))}")

        daily = data["daily"]
        dates, codes = daily.get("time", []), daily.get("weather_code", [])
        max_t, min_t = daily.get("temperature_2m_max", []), daily.get("temperature_2m_min", [])

        for i in range(min(5, len(dates))):
            card = self.forecast_cards[i]
            c_text, c_emoji = get_weather_condition(codes[i] if i < len(codes) else -1)
            try:
                dt = datetime.date.fromisoformat(dates[i])
                day_name, date_str = ("Today" if i == 0 else dt.strftime("%a")), dt.strftime("%b %d")
            except ValueError:
                day_name, date_str = f"Day {i+1}", dates[i]

            card["day"].config(text=day_name)
            card["date"].config(text=date_str)
            card["emoji"].config(text=c_emoji)
            card["cond"].config(text=c_text)
            card["temp_range"].config(text=f"{self._fmt_num(max_t[i])} / {self._fmt_num(min_t[i])}")


if __name__ == "__main__":
    app_root = tk.Tk()
    app = WeatherApp(app_root)
    app_root.mainloop()

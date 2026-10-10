import yaml
import sys

# 1. Update sector_metrics.yaml
with open("config/sector_metrics.yaml", "r", encoding="utf-8") as f:
    metrics = yaml.safe_load(f)

# Add real_estate and general
metrics["sectors"]["real_estate"] = {
    "revenue_yoy": {"weight": 0.25, "lower": -0.10, "upper": 0.30, "direction": "higher", "unit": "ratio"},
    "profit_yoy": {"weight": 0.25, "lower": -0.10, "upper": 0.30, "direction": "higher", "unit": "ratio"},
    "roe": {"weight": 0.20, "lower": 0.05, "upper": 0.25, "direction": "higher", "unit": "ratio"},
    "debt_ebitda": {"weight": 0.30, "lower": 1, "upper": 5, "direction": "lower", "unit": "multiple"},
}

metrics["sectors"]["general"] = {
    "revenue_yoy": {"weight": 0.25, "lower": -0.10, "upper": 0.30, "direction": "higher", "unit": "ratio"},
    "profit_yoy": {"weight": 0.25, "lower": -0.10, "upper": 0.30, "direction": "higher", "unit": "ratio"},
    "roe": {"weight": 0.25, "lower": 0.05, "upper": 0.25, "direction": "higher", "unit": "ratio"},
    "net_margin": {"weight": 0.25, "lower": 0.02, "upper": 0.20, "direction": "higher", "unit": "ratio"},
}

with open("config/sector_metrics.yaml", "w", encoding="utf-8") as f:
    yaml.dump(metrics, f, allow_unicode=True, sort_keys=False)


# 2. Update universe.yaml
vn30 = ["ACB","BID","BSR","CTG","FPT","GAS","GVR","HDB","HPG","LPB","MBB","MCH","MSN","MWG","SAB","SHB","SSB","SSI","STB","TCB","TCX","VCB","VHM","VIB","VIC","VJC","VNM","VPB","VPL","VRE"]

sector_map = {
    "ACB": "banking", "BID": "banking", "CTG": "banking", "HDB": "banking",
    "LPB": "banking", "MBB": "banking", "SHB": "banking", "SSB": "banking",
    "STB": "banking", "TCB": "banking", "VCB": "banking", "VIB": "banking", "VPB": "banking",
    "FPT": "technology", "MWG": "retail", "HPG": "steel", "SSI": "securities",
    "VNM": "consumer_staples", "MCH": "consumer_staples", "MSN": "consumer_staples", "SAB": "consumer_staples",
    "VHM": "real_estate", "VIC": "real_estate", "VRE": "real_estate", "VPL": "real_estate",
    "BSR": "general", "GAS": "general", "GVR": "general", "TCX": "general", "VJC": "general"
}

with open("config/universe.yaml", "r", encoding="utf-8") as f:
    universe = yaml.safe_load(f)

universe["max_symbols"] = 30
universe["selected"] = [{"symbol": sym, "sector": sector_map.get(sym, "general")} for sym in vn30]

with open("config/universe.yaml", "w", encoding="utf-8") as f:
    yaml.dump(universe, f, allow_unicode=True, sort_keys=False)


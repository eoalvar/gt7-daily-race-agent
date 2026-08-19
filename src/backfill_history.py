import requests
import json
import math
import re
import time
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from urllib.parse import (
    urljoin,
    urlparse,
    parse_qs,
    urlencode,
    urlunparse
)

GTSH_URL = "https://gtsh-rank.com/daily/"
MY_PSN_ID = "crazy_rooster74"

# Full GT7-era discovery window. 260 weeks reaches back beyond GT7 launch.
BACKFILL_WEEKS = 260
MAX_ARCHIVE_PAGES = 400

PAGE_SIZE = 100
MAX_LEADERBOARD_PAGES = 1000
REQUEST_DELAY_SECONDS = 0.08
HEADERS = {"User-Agent": "Mozilla/5.0 (GT7 Daily Race History Backfill)"}
DATA_DIR = Path("data")
WEEKLY_HISTORY_FILE = DATA_DIR / "weekly_rating_history.json"
BACKFILL_LOG_FILE = DATA_DIR / "backfill_history_log.txt"
SAO_PAULO = ZoneInfo("America/Sao_Paulo")

CAR_NAMES = {
    1563: "Renault Mégane Trophy '11", 2157: "Aston Martin V8 Vantage Gr.4",
    2161: "Nissan GT-R Gr.4", 2163: "Genesis Gr.4", 2164: "Ford Mustang Gr.4",
    2166: "Alfa Romeo 4C Gr.4", 3192: "Mercedes-Benz SLS AMG Gr.4",
    3231: "Volkswagen Scirocco Gr.4", 3245: "BMW M4 Gr.4", 3246: "Bugatti Veyron Gr.4",
    3247: "Chevrolet Corvette C7 Gr.4", 3248: "GT by Citroën Gr.4", 3249: "Dodge Viper Gr.4",
    3251: "Honda NSX Gr.4", 3252: "Jaguar F-type Gr.4", 3253: "Lamborghini Huracán Gr.4",
    3254: "Lexus RC F Gr.4", 3256: "Mazda Atenza Gr.4", 3257: "McLaren 650S Gr.4",
    3258: "Mitsubishi Lancer Evolution Final Gr.4", 3259: "Peugeot RCZ Gr.4",
    3260: "Renault Mégane Gr.4", 3261: "Subaru WRX Gr.4", 3262: "Toyota 86 Gr.4",
    3263: "Ferrari 458 Italia Gr.4", 3298: "Audi TT Cup '16",
    3310: "Porsche Cayman GT4 Clubsport '16", 3352: "Toyota GR Supra Racing Concept '18",
    3399: "Toyota GR Supra Race Car '19", 3477: "Nissan Silvia spec-R Aero (S15) Touring Car",
    3480: "Suzuki Swift Sport Gr.4", 3501: "Genesis G70 GR4", 3537: "Mazda3 Gr.4"
}

def score_to_laptime(score):
    if score is None: return "N/A"
    score = int(round(score)); minutes = score // 60000; seconds = (score % 60000) // 1000; milliseconds = score % 1000
    return f"{minutes}:{seconds:02d}.{milliseconds:03d}"

def get_user(driver): return driver.get("user", {})
def get_car_code(driver): return driver.get("ranking_stats", {}).get("car_code")
def get_car_name(car_code): return CAR_NAMES.get(car_code, f"Unknown car ({car_code})")
def get_online_id(driver):
    value = get_user(driver).get("np_online_id", "")
    return value.strip().lower() if isinstance(value, str) else ""
def find_my_driver(ranking, psn_id):
    target = psn_id.strip().lower()
    return next((d for d in ranking if get_online_id(d) == target), None)

def general_rating(rank, total):
    if rank is None or total is None or total <= 1: return None
    return max(0.0, min(10.0, 10 * (1 - (rank - 1) / (total - 1))))
def elite_rating(rank, total):
    if rank is None or total is None or total <= 1 or rank < 1: return None
    if rank == 1: return 10.0
    return max(0.0, min(10.0, 10 * (1 - math.log(rank) / math.log(total))))
def composite_rating(general, elite):
    return None if general is None or elite is None else general * 0.60 + elite * 0.40
def percentile_ahead(rank, total):
    return None if rank is None or total is None or total <= 1 else (total-rank)/(total-1)*100

def parse_date_from_text(text):
    match = re.search(r"(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})", text)
    if not match: return None
    try: return datetime.strptime(match.group(1), "%d %b %Y").replace(tzinfo=SAO_PAULO)
    except ValueError: return None

def monday_of_week(value):
    return (value - timedelta(days=value.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

def load_existing_history():
    if not WEEKLY_HISTORY_FILE.exists(): return []
    try:
        data = json.loads(WEEKLY_HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception: return []
def save_history(history):
    history.sort(key=lambda item: item.get("week_start", ""))
    WEEKLY_HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
def upsert_record(history, record):
    url = record.get("leaderboard_url")
    for i, existing in enumerate(history):
        if existing.get("leaderboard_url") == url: history[i] = record; return
    history.append(record)

def discover_race_c_events(session, cutoff_date, current_week):
    events = {}; reached_cutoff = False
    print("\nSEARCHING GTSH-RANK ARCHIVE\n" + "="*78)
    for page in range(1, MAX_ARCHIVE_PAGES + 1):
        page_url = GTSH_URL if page == 1 else f"{GTSH_URL}?page={page}&q="
        print(f"Reading archive page {page}...")
        response = session.get(page_url, timeout=30); response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        links = soup.select('a[href*="/daily/leaderboard?event="], a[href*="/daily/leaderboard/?event="]')
        if not links: break
        page_dates = []
        for link in links:
            parent = link.parent
            if parent is None: continue
            text = parent.get_text(" ", strip=True)
            if "Daily Race C" not in text: continue
            race_date = parse_date_from_text(text)
            if race_date is None: continue
            page_dates.append(race_date)
            if race_date > current_week or race_date < cutoff_date: continue
            href = link.get("href")
            if not href: continue
            full_url = urljoin(GTSH_URL, href)
            events[full_url] = {"date": race_date, "text": text, "url": full_url}
        if page_dates and min(page_dates) < cutoff_date - timedelta(days=14): reached_cutoff = True
        if reached_cutoff: break
        time.sleep(REQUEST_DELAY_SECONDS)
    result = list(events.values()); result.sort(key=lambda item: item["date"]); return result

def extract_json_variable(html, variable_name):
    for marker in [f"const {variable_name} = ", f"let {variable_name} = ", f"var {variable_name} = "]:
        start = html.find(marker)
        if start == -1: continue
        start += len(marker)
        try: return json.JSONDecoder().raw_decode(html[start:].lstrip())[0]
        except Exception: continue
    return None

def canonical_leaderboard_url(event_url):
    parsed = urlparse(event_url); path = parsed.path.rstrip("/")
    if path.endswith("/daily/leaderboard"): path += "/"
    return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, parsed.fragment))
def build_page_url(event_url, offset, limit=PAGE_SIZE):
    parsed = urlparse(canonical_leaderboard_url(event_url)); query = parse_qs(parsed.query, keep_blank_values=True)
    query["page_data"]=["1"]; query["offset"]=[str(offset)]; query["limit"]=[str(limit)]
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query,doseq=True), parsed.fragment))
def fetch_page(session,event_url,offset):
    response=session.get(build_page_url(event_url,offset,PAGE_SIZE),headers={"User-Agent":HEADERS["User-Agent"],"Accept":"application/json"},timeout=60); response.raise_for_status(); data=response.json()
    if not isinstance(data,dict): raise RuntimeError("Paged response is not a JSON object.")
    board=data.get("board")
    if not isinstance(board,list): raise RuntimeError("Paged response has no board array.")
    return {"board":board,"offset":int(data.get("offset",0)),"limit":int(data.get("limit",PAGE_SIZE)),"total":int(data.get("total",0)),"has_more":bool(data.get("has_more",False)),"leader_time":data.get("leader_time")}

def get_full_event_ranking(session,event_url):
    canonical_url=canonical_leaderboard_url(event_url); response=session.get(canonical_url,timeout=60); response.raise_for_status(); html=response.text
    initial=extract_json_variable(html,"initialServerPage")
    if isinstance(initial,dict) and isinstance(initial.get("board"),list):
        total=int(initial.get("total",0)); first=initial["board"]; all_drivers=list(first); seen={d.get("display_rank") for d in first}
        print(f"        page 1: {len(first)} drivers | total {total:,}"); offset=PAGE_SIZE
        for page_number in range(2,MAX_LEADERBOARD_PAGES+1):
            if total and offset>=total: break
            page=fetch_page(session,canonical_url,offset)
            if page["offset"]!=offset: raise RuntimeError(f"Pagination error: requested offset {offset}, received {page['offset']}.")
            board=page["board"]
            if not board: break
            for driver in board:
                rank=driver.get("display_rank")
                if rank not in seen: seen.add(rank); all_drivers.append(driver)
            if page_number<=3 or page_number%50==0:
                print(f"        page {page_number}: ranks {board[0].get('display_rank')}-{board[-1].get('display_rank')} | {len(all_drivers):,}/{total:,}")
            if not page["has_more"]: break
            offset += page["limit"]; time.sleep(REQUEST_DELAY_SECONDS)
        all_drivers.sort(key=lambda d:d.get("display_rank",999999999))
        if total and len(all_drivers)!=total: print(f"        WARNING: loaded {len(all_drivers):,} of {total:,}")
        return {"ranking":all_drivers,"total_records":total,"mode":"server_paged_page_data"}
    ranking=extract_json_variable(html,"initialRanking")
    if isinstance(ranking,list) and ranking:
        ranking.sort(key=lambda d:d.get("display_rank",999999999)); return {"ranking":ranking,"total_records":len(ranking),"mode":"full_initialRanking"}
    raise RuntimeError("Could not extract leaderboard.")

def build_record(event,ranking,total_records,extraction_mode):
    if not ranking:return None
    wr_score=ranking[0].get("score")
    if not wr_score:return None
    my_driver=find_my_driver(ranking,MY_PSN_ID)
    if not my_driver:return {"participated":False,"week_start":event["date"].date().isoformat(),"race":event["text"],"leaderboard_url":event["url"],"total_drivers":total_records,"extraction_mode":extraction_mode}
    my_score=my_driver.get("score"); my_rank=int(my_driver.get("display_rank")); my_user=get_user(my_driver); my_car_code=get_car_code(my_driver)
    general=general_rating(my_rank,total_records); elite=elite_rating(my_rank,total_records); composite=composite_rating(general,elite); ahead=percentile_ahead(my_rank,total_records)
    top_percent=my_rank/total_records*100; wr_percentage=my_score/wr_score*100
    same_car=[d for d in ranking if get_car_code(d)==my_car_code]; same_car_rank=next((i for i,d in enumerate(same_car,start=1) if get_online_id(d)==MY_PSN_ID.lower()),None)
    my_country=my_user.get("country_code"); country_group=[d for d in ranking if get_user(d).get("country_code")==my_country]; country_rank=next((i for i,d in enumerate(country_group,start=1) if get_online_id(d)==MY_PSN_ID.lower()),None)
    return {"participated":True,"week_start":event["date"].date().isoformat(),"final_snapshot":"archived_leaderboard","finalization_mode":"historical_backfill","extraction_mode":extraction_mode,"race":event["text"],"leaderboard_url":event["url"],"general_score":general,"elite_score":elite,"composite_rating":composite,"position":my_rank,"total_drivers":total_records,"top_percent":top_percent,"percentile_ahead":ahead,"wr_percentage":wr_percentage,"laptime":score_to_laptime(my_score),"score_ms":my_score,"world_record":score_to_laptime(wr_score),"world_record_ms":wr_score,"gap_to_wr_ms":my_score-wr_score,"car":get_car_name(my_car_code),"car_code":my_car_code,"country":my_country,"driver_rating":my_user.get("driver_rating"),"country_rank":country_rank,"country_total":len(country_group),"same_car_rank":same_car_rank,"same_car_total":len(same_car)}

def metric_change(records,key,higher_is_better=True):
    values=[r.get(key) for r in records if isinstance(r.get(key),(int,float))]
    if len(values)<2:return None
    first,last=values[0],values[-1]; change=last-first; return {"first":first,"last":last,"change":change,"improvement":change if higher_is_better else -change}

def main():
    DATA_DIR.mkdir(parents=True,exist_ok=True); now=datetime.now(SAO_PAULO); current_monday=monday_of_week(now); cutoff_date=current_monday-timedelta(weeks=BACKFILL_WEEKS)
    print("\nGT7 DAILY RACE C - FULL GT7 HISTORY BACKFILL\n"+"="*78); print(f"PSN ID: {MY_PSN_ID}\nFrom: {cutoff_date.date()}\nTo: {current_monday.date()}\n")
    session=requests.Session(); session.headers.update(HEADERS); events=discover_race_c_events(session,cutoff_date,current_monday)
    print(f"\nDaily Race C events found: {len(events)}\n")
    if not events: raise RuntimeError("No historical events found.")
    history=load_existing_history(); participated=[]; missing=[]; failures=[]
    for number,event in enumerate(events,start=1):
        print(f"[{number}/{len(events)}] {event['date'].date()}\n    {event['text'][:150]}")
        try:
            result=get_full_event_ranking(session,event["url"]); ranking=result["ranking"]; total=result["total_records"]
            print(f"    Mode: {result['mode']}\n    Drivers loaded: {len(ranking):,}\n    Total: {total:,}")
            record=build_record(event,ranking,total,result["mode"])
            if not record: failures.append(event); print("    ERROR: invalid record"); continue
            if not record.get("participated"): missing.append(record); print(f"    {MY_PSN_ID}: NOT FOUND"); continue
            participated.append(record); upsert_record(history,record)
            print(f"    FOUND: {MY_PSN_ID}\n    Position: #{record['position']:,}/{record['total_drivers']:,}\n    Time: {record['laptime']}\n    Car: {record['car']}\n    General: {record['general_score']:.2f}\n    Elite: {record['elite_score']:.2f}\n    Composite: {record['composite_rating']:.2f}\n    Top: {record['top_percent']:.2f}%\n    WR: {record['wr_percentage']:.3f}%")
        except Exception as error:
            failures.append({"date":event["date"],"url":event["url"],"error":str(error)}); print(f"    ERROR: {error}")
        time.sleep(REQUEST_DELAY_SECONDS)
    save_history(history); participated.sort(key=lambda i:i["week_start"])
    lines=["GT7 DAILY RACE C - FULL HISTORICAL BACKFILL","="*78,f"Period searched: {cutoff_date.date()} to {current_monday.date()}",f"Race C events found: {len(events)}",f"Participated: {len(participated)}",f"PSN not found: {len(missing)}",f"Extraction failures: {len(failures)}"]
    if participated:
        lines += ["","HISTORICAL RATINGS"]
        for r in participated: lines.append(f"{r['week_start']} | G {r['general_score']:.2f} | E {r['elite_score']:.2f} | C {r['composite_rating']:.2f} | Top {r['top_percent']:.2f}% | WR {r['wr_percentage']:.3f}% | #{r['position']:,}/{r['total_drivers']:,} | {r['car']}")
        metrics=[("General",metric_change(participated,"general_score")),("Elite",metric_change(participated,"elite_score")),("Composite",metric_change(participated,"composite_rating"))]
        if any(v for _,v in metrics): lines += ["","CHANGE ACROSS AVAILABLE HISTORY"]
        for name,v in metrics:
            if v: lines.append(f"{name}: {v['first']:.2f} -> {v['last']:.2f} ({v['change']:+.2f})")
        wr=metric_change(participated,"wr_percentage",False)
        if wr:
            direction="improvement" if wr["improvement"]>0 else "deterioration" if wr["improvement"]<0 else "unchanged"
            lines.append(f"WR %: {wr['first']:.3f}% -> {wr['last']:.3f}% ({abs(wr['change']):.3f} pp {direction})")
    if missing:
        lines += ["","WEEKS WITHOUT A RECORDED LAP"]+[r["week_start"] for r in missing]
    if failures:
        lines += ["","FAILED EVENTS"]
        for f in failures:
            if isinstance(f,dict):
                d=f.get("date"); date_text=str(d.date()) if hasattr(d,"date") else str(d); lines.append(f"{date_text} | {f.get('error','Unknown error')}")
    lines += ["",f"Saved to: {WEEKLY_HISTORY_FILE}","="*78]
    report="\n".join(lines); BACKFILL_LOG_FILE.write_text(report,encoding="utf-8"); print("\n"+report)

if __name__ == "__main__":
    main()

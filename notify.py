"""Optional email delivery. Configure SMTP_HOST, SMTP_PORT, SMTP_USER,
SMTP_PASSWORD, REPORT_TO as GitHub Actions secrets."""
import json, os, smtplib
from email.message import EmailMessage

def main():
    required = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "REPORT_TO"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        print("Email skipped; missing GitHub secrets: " + ", ".join(missing))
        return
    data = json.load(open("docs/data/latest.json"))
    msg = EmailMessage()
    msg["Subject"] = f"Nifty Momentum Screener — {data['latest_market_date']}"
    msg["From"] = os.environ["SMTP_USER"]
    msg["To"] = os.environ["REPORT_TO"]
    lines = [
        f"Market date: {data['latest_market_date']}",
        f"Data coverage: {data['success_count']}/{data['universe_count']}",
        "",
        "SHORTLIST (within 10% of ATH; momentum >=80; above 50/200 DMA)",
        "Index | ATH distance | Momentum | RSI | Current | ATH",
    ]
    for x in data["shortlist"]:
        lines.append(
            f"{x['index']} | {x['distance_from_ath_pct']}% | {x['momentum_score']} | "
            f"{x['rsi_14']} | {x['current']} | {x['ath']}"
        )
    if not data["shortlist"]:
        lines.append("No indices passed all shortlist filters today.")
    lines += ["", "Data source: " + data["source"], "", "Open your saved dashboard link for the full report."]
    msg.set_content("\n".join(lines))
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"])) as s:
        s.starttls()
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.send_message(msg)
    print("Daily email sent.")

if __name__ == "__main__":
    main()

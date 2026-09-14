import httpx

def main():
    p = httpx.get("http://127.0.0.1:8000/api/v1/portfolio").json()
    positions = {pos["ticker"]: pos for pos in p.get("positions", [])}
    
    sig_resp = httpx.get("http://127.0.0.1:8000/api/v1/scanner/signals?limit=100").json()
    preds = sig_resp.get("signals", []) if isinstance(sig_resp, dict) else sig_resp
    pred_map = {x["ticker"]: x for x in preds}

    tot_val = p.get("total_value", 964050.22)
    cash = p.get("cash", 213862.39)

    print("=" * 75)
    print("       CANLI PORTFOY VE OTONOM FIRSATLAR KARSILASTIRMA RAPORU         ")
    print("=" * 75)
    print(f"Toplam Portfoy: {tot_val:,.2f} TL | Nakit: {cash:,.2f} TL (%{cash/tot_val*100:.1f}) | Hisse: {len(positions)}")
    print("-" * 75)
    print(f"{'#':<3} {'Hisse':<7} {'Skor':>6} {'Beklenen':>10} {'Tutar':>13} {'Pay':>7} {'Strateji / Sinyal':<18}")
    print("-" * 75)

    # Sort positions by market value descending
    sorted_pos = sorted(positions.items(), key=lambda x: x[1]["quantity"] * x[1]["current_price"], reverse=True)

    for idx, (t, pos) in enumerate(sorted_pos, 1):
        sc = pred_map.get(t, {}).get("score", 0.0)
        exp_r = pred_map.get(t, {}).get("expected_return_pct", 0.0)
        stype = pred_map.get(t, {}).get("signal_type", pred_map.get(t, {}).get("strategy_type", "-"))
        val = pos["quantity"] * pos["current_price"]
        w = (val / tot_val) * 100.0
        print(f"{idx:>2}. {t:<7} {sc:>6.1f} %{exp_r:>8.1f} {val:>10,.2f} TL %{w:>5.1f} {stype:<18}")

    print("-" * 75)

if __name__ == "__main__":
    main()

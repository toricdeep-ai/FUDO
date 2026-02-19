"""FUDO - メインUI（Streamlit）"""
from __future__ import annotations

import streamlit as st
st.set_page_config(page_title="FUDO", page_icon="📊", layout="wide")

try:
    import pandas as pd
    from datetime import date, datetime, timedelta, timezone

    JST = timezone(timedelta(hours=9))

    def today_jst():
        return datetime.now(JST).date()

    import database as db
    from analytics import (
        judge_grade, calc_lot_r, calc_expected_value,
        calc_entry_type_stats, calc_stop_reason_stats, calc_quality_stats,
        calc_trade_statistics, load_config,
    )
    try:
        from rss_monitor import get_rss_prices, get_rss_board, check_surge_alerts, check_price_alerts, check_fushi_alerts
    except Exception:
        get_rss_prices = None
        get_rss_board = None
        check_surge_alerts = None
        check_price_alerts = None
        check_fushi_alerts = None
except Exception as e:
    st.error(f"Import error: {e}")
    import traceback
    st.code(traceback.format_exc())
    st.stop()

config = load_config()

# ===== パスワード保護 =====
_auth_password = config.get("auth", {}).get("password", "") or "samuraiakb1A"
if _auth_password:
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    if not st.session_state["authenticated"]:
        st.title("FUDO - ログイン")
        pwd = st.text_input("パスワードを入力してください", type="password", key="_login_pwd")
        if st.button("ログイン", key="_login_btn"):
            if pwd == _auth_password:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("パスワードが違います")
        st.stop()

st.title("FUDO - 銘柄管理ツール")
quality_options = config.get("meigara_quality_options", [])
teii_options = config.get("teii_taishaku_options", ["低位", "貸借", "なし"])
entry_types = config.get("entry_types", [])
entry_positions = config.get("entry_positions", [])
stop_reasons_labels = config.get("exit_strategy_reasons", [])
r_unit = config.get("risk", {}).get("r_unit", 10000)

# ===== サイドバー：銘柄追加フォーム =====
with st.sidebar:
    st.header("銘柄追加")
    with st.form("add_stock_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            input_name = st.text_input("銘柄名")
        with col2:
            input_ticker = st.text_input("証券コード")

        input_date = st.date_input("日付", value=today_jst())
        input_market_cap = st.slider("時価総額（億円）", min_value=0, max_value=1000, value=0, step=1)
        input_margin = st.slider("信用買残（%）", min_value=0.0, max_value=100.0, value=0.0, step=0.1)
        input_fushi = st.text_input("節目（例: 1500, 1450）")
        input_pts = st.slider("PTS出来高", min_value=0, max_value=1000000, value=0, step=100)
        input_prev_sell_vol = st.number_input("前日売り総量", min_value=0, step=100, key="input_prev_sell_vol")
        input_disclosure = st.number_input("日々公表カウント", min_value=0, max_value=3, step=1)
        input_mashitanpo = st.selectbox("増し担保規制", ["なし", "あり"])
        input_hiduke = st.checkbox("日足位置が良い")
        input_teii = st.selectbox("低位 / 貸借", teii_options)
        input_quality = st.selectbox("銘柄質", quality_options)
        input_memo = st.text_area("一言メモ", height=68)

        submitted = st.form_submit_button("追加", use_container_width=True)

    if submitted and input_name and input_ticker:
        market_cap_yen = input_market_cap * 100_000_000

        grade, max_r = judge_grade(
            market_cap=market_cap_yen,
            hiduke_position_good=input_hiduke,
            teii_or_taishaku=input_teii,
        )

        lot_text = f"{grade}級 / 最大{max_r}R（¥{max_r * r_unit:,}）"

        stock_id = db.add_stock({
            "date": str(input_date),
            "name": input_name,
            "ticker": input_ticker,
            "market_cap": market_cap_yen,
            "margin_buy_ratio": input_margin,
            "fushi": input_fushi,
            "pts_volume": input_pts,
            "daily_disclosure_count": input_disclosure,
            "hiduke_position_good": 1 if input_hiduke else 0,
            "teii_or_taishaku": input_teii,
            "meigara_quality": input_quality,
            "grade": grade,
            "max_r": max_r,
            "lot_strategy": lot_text,
            "memo": f"[増担:{input_mashitanpo}] {input_memo}" if input_mashitanpo == "あり" else input_memo,
            "prev_day_sell_volume": input_prev_sell_vol,
        })
        st.success(f"追加しました（ID: {stock_id}、{lot_text}）")
        st.rerun()

# ===== メインエリア =====
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
    "📋 ウォッチリスト",
    "📝 トレード記録",
    "📊 エントリー分析",
    "🔬 統計",
    "🧮 ロット計算",
    "📈 期待値計算",
    "📢 適時開示",
    "📡 監視パネル",
    "📓 Notion連携",
])

# --- タブ1: ウォッチリスト ---
with tab1:
    col_date, col_refresh = st.columns([3, 1])
    with col_date:
        filter_date = st.date_input("日付フィルタ", value=today_jst(), key="filter_date")
    with col_refresh:
        st.write("")
        st.write("")
        if st.button("全件表示"):
            filter_date = None

    stocks = db.get_stocks(str(filter_date) if filter_date else None)

    if stocks:
        df = pd.DataFrame(stocks)
        display_cols = {
            "id": "ID", "date": "日付", "name": "銘柄名", "ticker": "コード",
            "market_cap": "時価総額", "margin_buy_ratio": "信用買残%",
            "fushi": "節目", "pts_volume": "PTS出来高",
            "prev_day_sell_volume": "前日売り総量",
            "daily_disclosure_count": "日々公表",
            "hiduke_position_good": "日足位置", "teii_or_taishaku": "低位/貸借",
            "meigara_quality": "銘柄質", "grade": "級",
            "max_r": "最大R", "lot_strategy": "ロット戦略",
        }
        df_display = df[[c for c in display_cols if c in df.columns]].rename(columns=display_cols)

        if "時価総額" in df_display.columns:
            df_display["時価総額"] = df_display["時価総額"].apply(
                lambda x: f"{x / 100_000_000:.0f}億" if pd.notna(x) and x else ""
            )
        if "日足位置" in df_display.columns:
            df_display["日足位置"] = df_display["日足位置"].apply(lambda x: "○" if x else "×")

        def grade_color(val):
            colors = {
                "SS": "background-color: #ff6b6b; color: white; font-weight: bold",
                "S": "background-color: #ffa94d; font-weight: bold",
                "A": "background-color: #69db7c",
            }
            return colors.get(val, "")

        styled = df_display.style.applymap(grade_color, subset=["級"] if "級" in df_display.columns else [])
        st.dataframe(styled, use_container_width=True, hide_index=True)

        # メモ一覧（編集可能）
        with st.expander("メモ一覧（編集可能）", expanded=False):
            for s in stocks:
                memo = s.get("memo", "") or ""
                st.markdown(f"**{s['name']}（{s['ticker']}）** ID:{s['id']}")
                new_memo = st.text_area(
                    f"メモ_{s['id']}",
                    value=memo,
                    height=100,
                    key=f"memo_edit_{s['id']}",
                    label_visibility="collapsed",
                )
                if new_memo != memo:
                    if st.button(f"保存", key=f"memo_save_{s['id']}"):
                        db.update_stock(s["id"], {"memo": new_memo})
                        st.success(f"{s['name']} のメモを保存しました")
                        st.rerun()
                st.markdown("---")

        with st.expander("銘柄を削除"):
            del_id = st.number_input("削除するID", min_value=1, step=1, key="del_id")
            if st.button("削除実行"):
                db.delete_stock(del_id)
                st.success(f"ID {del_id} を削除しました")
                st.rerun()
    else:
        st.info("銘柄が登録されていません。サイドバーから追加してください。")

# --- タブ2: トレード記録 ---
with tab2:
    st.subheader("トレード記録")

    with st.form("add_trade_form", clear_on_submit=True):
        st.markdown("##### 基本情報")
        tc1, tc2, tc3 = st.columns(3)
        with tc1:
            t_date = st.date_input("日付", value=today_jst(), key="t_date")
            t_name = st.text_input("銘柄名", key="t_name")
            t_ticker = st.text_input("証券コード", key="t_ticker")
        with tc2:
            t_grade = st.selectbox("級", ["SS", "S", "A"], key="t_grade")
            t_entry_type = st.selectbox("エントリー分類", entry_types, key="t_entry_type")
            t_entry_pos = st.selectbox("エントリー位置", entry_positions, key="t_entry_pos")
            t_quality = st.selectbox("銘柄質", quality_options, key="t_quality")
            t_lot = st.number_input("ロット（株数）", min_value=0, step=100, key="t_lot")
        with tc3:
            t_entry_price = st.text_input("エントリー価格", value="0", key="t_entry_price")
            t_exit_price = st.text_input("手仕舞い価格", value="0", key="t_exit_price")
            t_result = st.selectbox("結果", ["win", "lose"], key="t_result")

        st.markdown("##### 出口戦略")
        sc1, sc2, sc3, sc4 = st.columns(4)
        with sc1:
            t_stop1 = st.checkbox("抑え玉喰わない", key="t_stop1")
        with sc2:
            t_stop2 = st.checkbox("買い板吸収しない", key="t_stop2")
        with sc3:
            t_stop3 = st.checkbox("買い板消える", key="t_stop3")
        with sc4:
            t_stop4 = st.checkbox("節目ブレイク後勢いなし", key="t_stop4")
        sc5, sc6, sc7, sc8 = st.columns(4)
        with sc5:
            t_stop5 = st.checkbox("買い板はめこみ", key="t_stop5")
        with sc6:
            t_stop6 = st.checkbox("指値ケア反応悪く下振り懸念", key="t_stop6")
        with sc7:
            t_stop7 = st.checkbox("買い板弱くなる", key="t_stop7")
        with sc8:
            t_stop8 = st.checkbox("上を買わなくなる", key="t_stop8")
        sc9, sc10, _, _ = st.columns(4)
        with sc9:
            t_stop9 = st.checkbox("夜間PTS", key="t_stop9")
        with sc10:
            t_stop10 = st.checkbox("持ち越し翌日売り", key="t_stop10")

        t_memo = st.text_area("メモ", height=68, key="t_memo")
        t_submitted = st.form_submit_button("トレード記録を保存", use_container_width=True)

    if t_submitted and t_name and t_ticker:
        try:
            _entry_p = float(t_entry_price) if t_entry_price else 0
            _exit_p = float(t_exit_price) if t_exit_price else 0
        except ValueError:
            _entry_p = 0
            _exit_p = 0
        pnl = (_exit_p - _entry_p) * t_lot if _entry_p and _exit_p and t_lot else 0
        trade_id = db.add_trade({
            "date": str(t_date),
            "name": t_name,
            "ticker": t_ticker,
            "grade": t_grade,
            "entry_type": t_entry_type,
            "entry_position": t_entry_pos,
            "entry_price": _entry_p,
            "exit_price": _exit_p,
            "lot": t_lot,
            "pnl": pnl,
            "result": t_result,
            "stop_osaedama": 1 if t_stop1 else 0,
            "stop_itakyushu": 1 if t_stop2 else 0,
            "stop_itakieru": 1 if t_stop3 else 0,
            "stop_fushi_noforce": 1 if t_stop4 else 0,
            "stop_hamekomi": 1 if t_stop5 else 0,
            "stop_sashene_care": 1 if t_stop6 else 0,
            "stop_ita_yowaku": 1 if t_stop7 else 0,
            "stop_ue_kawanai": 1 if t_stop8 else 0,
            "stop_yakan_pts": 1 if t_stop9 else 0,
            "stop_mochikoshi": 1 if t_stop10 else 0,
            "meigara_quality": t_quality,
            "memo": t_memo,
        })
        pnl_text = f"+¥{pnl:,.0f}" if pnl >= 0 else f"-¥{abs(pnl):,.0f}"
        st.success(f"記録しました（ID: {trade_id}、損益: {pnl_text}）")
        st.rerun()

    # --- 日付検索 ---
    st.markdown("---")
    st.markdown("##### トレード履歴")
    srch_c1, srch_c2, srch_c3 = st.columns([2, 2, 1])
    with srch_c1:
        trade_search_date = st.date_input("日付で検索", value=None, key="trade_search_date")
    with srch_c2:
        st.write("")
        st.write("")
    with srch_c3:
        st.write("")
        st.write("")
        trade_show_all = st.button("全件表示", key="trade_show_all")

    if trade_show_all:
        trades = db.get_trades()
    elif trade_search_date:
        trades = db.get_trades(str(trade_search_date))
    else:
        trades = db.get_trades()

    if trades:
        df_t = pd.DataFrame(trades)
        show_cols = {
            "id": "ID", "date": "日付", "name": "銘柄名", "ticker": "コード",
            "grade": "級", "entry_type": "分類", "entry_position": "位置",
            "meigara_quality": "銘柄質",
            "entry_price": "IN", "exit_price": "OUT",
            "lot": "ロット", "pnl": "損益", "result": "結果",
            "stop_osaedama": "抑え玉", "stop_itakyushu": "板吸収",
            "stop_itakieru": "板消え", "stop_fushi_noforce": "勢いなし",
            "stop_hamekomi": "はめこみ", "stop_sashene_care": "指値ケア",
            "stop_ita_yowaku": "板弱化",
            "stop_ue_kawanai": "上買わず", "stop_yakan_pts": "夜間PTS",
            "stop_mochikoshi": "持越翌日売",
            "memo": "メモ",
        }
        df_show = df_t[[c for c in show_cols if c in df_t.columns]].rename(columns=show_cols)

        # チェックボックス列を○×表示
        for col in ["抑え玉", "板吸収", "板消え", "勢いなし", "はめこみ", "指値ケア", "板弱化", "上買わず", "夜間PTS", "持越翌日売"]:
            if col in df_show.columns:
                df_show[col] = df_show[col].apply(lambda x: "✓" if x else "")

        # 結果に色付け
        def result_color(val):
            if val == "win":
                return "background-color: #69db7c; font-weight: bold"
            elif val == "lose":
                return "background-color: #ff6b6b; color: white"
            return ""

        styled_t = df_show.style.applymap(result_color, subset=["結果"] if "結果" in df_show.columns else [])
        st.dataframe(styled_t, use_container_width=True, hide_index=True)
        st.caption(f"表示件数: {len(trades)}件")

        # --- トレード記録を編集 ---
        with st.expander("トレード記録を編集"):
            edit_tid = st.number_input("編集するID", min_value=1, step=1, key="edit_tid")
            if st.button("読み込み", key="load_trade_btn"):
                t_data = db.get_trade_by_id(edit_tid)
                if t_data:
                    st.session_state["edit_trade_data"] = t_data
                else:
                    st.error("指定されたIDのトレードが見つかりません")

            if st.session_state.get("edit_trade_data"):
                ed = st.session_state["edit_trade_data"]
                with st.form("edit_trade_form"):
                    st.markdown(f"**ID: {ed['id']}** を編集中")
                    ec1, ec2, ec3 = st.columns(3)
                    with ec1:
                        ed_date = st.date_input("日付", value=date.fromisoformat(ed["date"]) if ed.get("date") else today_jst(), key="ed_date")
                        ed_name = st.text_input("銘柄名", value=ed.get("name", ""), key="ed_name")
                        ed_ticker = st.text_input("証券コード", value=ed.get("ticker", ""), key="ed_ticker")
                    with ec2:
                        _grades = ["SS", "S", "A"]
                        ed_grade = st.selectbox("級", _grades, index=_grades.index(ed["grade"]) if ed.get("grade") in _grades else 0, key="ed_grade")
                        ed_entry_type = st.selectbox("エントリー分類", entry_types, index=entry_types.index(ed["entry_type"]) if ed.get("entry_type") in entry_types else 0, key="ed_entry_type")
                        ed_entry_pos = st.selectbox("エントリー位置", entry_positions, index=entry_positions.index(ed["entry_position"]) if ed.get("entry_position") in entry_positions else 0, key="ed_entry_pos")
                        ed_quality = st.selectbox("銘柄質", quality_options, index=quality_options.index(ed["meigara_quality"]) if ed.get("meigara_quality") in quality_options else 0, key="ed_quality")
                        ed_lot = st.number_input("ロット", value=ed.get("lot", 0), min_value=0, step=100, key="ed_lot")
                    with ec3:
                        ed_entry_price = st.text_input("エントリー価格", value=str(ed.get("entry_price", 0)), key="ed_entry_price")
                        ed_exit_price = st.text_input("手仕舞い価格", value=str(ed.get("exit_price", 0)), key="ed_exit_price")
                        ed_result = st.selectbox("結果", ["win", "lose"], index=0 if ed.get("result") == "win" else 1, key="ed_result")
                    ed_memo = st.text_area("メモ", value=ed.get("memo", "") or "", key="ed_memo")
                    ed_submitted = st.form_submit_button("更新", use_container_width=True)

                if ed_submitted:
                    try:
                        _ed_entry_p = float(ed_entry_price) if ed_entry_price else 0
                        _ed_exit_p = float(ed_exit_price) if ed_exit_price else 0
                    except ValueError:
                        _ed_entry_p = 0
                        _ed_exit_p = 0
                    ed_pnl = (_ed_exit_p - _ed_entry_p) * ed_lot if _ed_entry_p and _ed_exit_p and ed_lot else 0
                    db.update_trade(ed["id"], {
                        "date": str(ed_date),
                        "name": ed_name,
                        "ticker": ed_ticker,
                        "grade": ed_grade,
                        "entry_type": ed_entry_type,
                        "entry_position": ed_entry_pos,
                        "entry_price": _ed_entry_p,
                        "exit_price": _ed_exit_p,
                        "lot": ed_lot,
                        "pnl": ed_pnl,
                        "result": ed_result,
                        "meigara_quality": ed_quality,
                        "memo": ed_memo,
                    })
                    st.success(f"ID {ed['id']} を更新しました")
                    st.session_state.pop("edit_trade_data", None)
                    st.rerun()

        with st.expander("トレード記録を削除"):
            del_tid = st.number_input("削除するID", min_value=1, step=1, key="del_tid")
            if st.button("削除実行", key="del_trade_btn"):
                db.delete_trade(del_tid)
                st.success(f"ID {del_tid} を削除しました")
                st.rerun()
    else:
        st.info("トレード記録がありません。上のフォームから追加してください。")

# --- タブ3: エントリー分析 ---
with tab3:
    st.subheader("エントリー分類別 勝率")

    all_trades = db.get_trades()

    if all_trades:
        # エントリー分類別 勝率テーブル
        entry_stats = calc_entry_type_stats(all_trades)
        df_es = pd.DataFrame(entry_stats)
        df_es = df_es.rename(columns={
            "entry_type": "エントリー分類",
            "total": "回数",
            "wins": "勝ち",
            "losses": "負け",
            "win_rate": "勝率",
            "total_pnl": "累計損益",
            "avg_pnl": "平均損益",
            "avg_win": "平均利益",
            "avg_loss": "平均損失",
            "expected_value": "期待値",
            "profit_factor": "PF",
        })

        # 勝率を%表示
        df_es["勝率"] = df_es["勝率"].apply(lambda x: f"{x * 100:.1f}%")
        for col in ["累計損益", "平均損益", "平均利益", "平均損失", "期待値"]:
            df_es[col] = df_es[col].apply(lambda x: f"¥{x:,.0f}")

        st.dataframe(df_es, use_container_width=True, hide_index=True)

        # 銘柄質別 勝率
        st.markdown("---")
        st.subheader("銘柄質別 勝率")

        quality_stats = calc_quality_stats(all_trades)
        df_qs = pd.DataFrame(quality_stats)
        df_qs = df_qs.rename(columns={
            "quality": "銘柄質",
            "total": "回数", "wins": "勝ち", "losses": "負け",
            "win_rate": "勝率", "total_pnl": "累計損益",
            "avg_pnl": "平均損益", "avg_win": "平均利益",
            "avg_loss": "平均損失", "expected_value": "期待値",
            "profit_factor": "PF",
        })
        df_qs["勝率"] = df_qs["勝率"].apply(lambda x: f"{x * 100:.1f}%")
        for col in ["累計損益", "平均損益", "平均利益", "平均損失", "期待値"]:
            df_qs[col] = df_qs[col].apply(lambda x: f"¥{x:,.0f}")

        st.dataframe(df_qs, use_container_width=True, hide_index=True)

        # 損切り理由分析
        st.markdown("---")
        st.subheader("出口戦略 発生率")

        stop_stats = calc_stop_reason_stats(all_trades)
        df_ss = pd.DataFrame(stop_stats)
        df_ss = df_ss.rename(columns={
            "reason": "出口戦略",
            "count": "発生回数",
            "ratio": "発生率",
        })
        df_ss["発生率"] = df_ss["発生率"].apply(lambda x: f"{x * 100:.1f}%")

        st.dataframe(df_ss, use_container_width=True, hide_index=True)

        # 棒グラフ
        loss_trades = [t for t in all_trades if t.get("result") != "win"]
        if loss_trades:
            chart_data = pd.DataFrame(stop_stats)
            chart_data = chart_data.set_index("reason")["count"]
            st.bar_chart(chart_data)
    else:
        st.info("トレード記録がありません。「トレード記録」タブから追加してください。")

# --- タブ4: 統計 ---
with tab4:
    st.subheader("トレード統計（Rベース）")

    stat_trades = db.get_trades()

    if stat_trades:
        stats = calc_trade_statistics(stat_trades)
        ru = stats["r_unit"]

        # ===== 精度表示 =====
        accuracy = stats["accuracy"]
        if "高精度" in accuracy:
            st.success(f"📏 精度: {accuracy}")
        elif "中精度" in accuracy:
            st.info(f"📏 精度: {accuracy}")
        elif "低精度" in accuracy or "参考値" in accuracy:
            st.warning(f"📏 精度: {accuracy}")
        else:
            st.error(f"📏 精度: {accuracy}")

        # ===== メイン指標 =====
        st.markdown("##### 期待値 = (勝率 × 平均利益R) − (負率 × 平均損失R)")
        m1, m2, m3, m4 = st.columns(4)
        ev_r = stats["expected_value_r"]
        m1.metric("期待値", f"{ev_r:+.2f} R", delta=f"¥{ev_r * ru:+,.0f}")
        m2.metric("勝率", f"{stats['win_rate'] * 100:.1f}%")
        m3.metric("PF", f"{stats['profit_factor']:.2f}")
        m4.metric("累計損益", f"{stats['total_pnl_r']:+.1f} R", delta=f"¥{stats['total_pnl']:+,.0f}")

        # ===== 詳細指標 =====
        st.markdown("---")
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("トレード数", f"{stats['total']}回")
        d2.metric(f"勝ち / 負け", f"{stats['wins']}W / {stats['losses']}L")
        d3.metric("最大連勝", f"{stats['consecutive_wins']}連勝")
        d4.metric("最大連敗", f"{stats['consecutive_losses']}連敗")

        e1, e2, e3, e4 = st.columns(4)
        e1.metric("平均利益", f"{stats['avg_win_r']:.2f} R", delta=f"¥{stats['avg_win_r'] * ru:,.0f}")
        e2.metric("平均損失", f"{stats['avg_loss_r']:.2f} R", delta=f"-¥{stats['avg_loss_r'] * ru:,.0f}", delta_color="inverse")
        e3.metric("最大利益", f"{stats['max_win_r']:.2f} R")
        e4.metric("最大損失", f"{stats['max_loss_r']:.2f} R")

        st.metric("損益分岐勝率", f"{stats['breakeven_winrate'] * 100:.1f}%")

        # ===== 次回許容ロット =====
        st.markdown("---")
        st.subheader("次回許容ロット")

        lot_info = stats["next_lot_info"]
        st.info(f"💡 {lot_info.get('reason', '')}")

        nl1, nl2, nl3 = st.columns(3)
        nl1.metric("SS級", f"最大 {lot_info.get('SS', '-')}R（¥{lot_info.get('SS', 0) * ru:,}）")
        nl2.metric("S級", f"最大 {lot_info.get('S', '-')}R（¥{lot_info.get('S', 0) * ru:,}）")
        nl3.metric("A級", f"最大 {lot_info.get('A', '-')}R（¥{lot_info.get('A', 0) * ru:,}）")

        # ===== 勝ちトレード抽出 =====
        st.markdown("---")
        st.subheader("勝ちトレード抽出")

        win_trades = stats["win_trades"]
        if win_trades:
            df_win = pd.DataFrame(win_trades)
            win_cols = {
                "date": "日付", "name": "銘柄名", "ticker": "コード",
                "grade": "級", "entry_type": "分類", "meigara_quality": "銘柄質",
                "entry_price": "IN", "exit_price": "OUT",
                "lot": "ロット", "pnl": "損益",
            }
            df_win_show = df_win[[c for c in win_cols if c in df_win.columns]].rename(columns=win_cols)
            if "損益" in df_win_show.columns:
                df_win_show["損益R"] = df_win_show["損益"].apply(lambda x: f"{x / ru:+.1f}R")
                df_win_show["損益"] = df_win_show["損益"].apply(lambda x: f"¥{x:+,.0f}")
            st.dataframe(df_win_show, use_container_width=True, hide_index=True)
        else:
            st.info("勝ちトレードはまだありません。")
    else:
        st.info("トレード記録がありません。「トレード記録」タブから追加してください。")

# --- タブ5: ロット計算 ---
with tab5:
    st.subheader("Rベース ロット計算")

    col1, col2 = st.columns(2)
    with col1:
        lot_grade = st.selectbox("級", ["SS", "S", "A"], key="lot_grade")
        grade_r_map = {"SS": 10, "S": 5, "A": 1}
        lot_default_r = grade_r_map[lot_grade]
        lot_max_r = st.slider("R数", min_value=1, max_value=20, value=lot_default_r, step=1, key="lot_r_slider")
        lot_r_unit = st.slider("1Rの金額（円）", min_value=1000, max_value=100000, value=r_unit, step=1000, key="lot_r_unit")
        st.info(f"最大 {lot_max_r}R = ¥{lot_max_r * lot_r_unit:,}")
    with col2:
        lot_ticker_input = st.text_input("証券コード（ウォッチリスト登録用）", value="", key="lot_ticker_input", placeholder="例: 6920")
        lot_entry_str = st.text_input("エントリー価格（円）", value="1000", key="lot_entry")
        lot_stop_str = st.text_input("損切り価格（円）", value="950", key="lot_stop")

    if st.button("計算", key="calc_lot"):
        try:
            lot_entry = float(lot_entry_str) if lot_entry_str else 0
            lot_stop = float(lot_stop_str) if lot_stop_str else 0
        except ValueError:
            st.error("数字を入力してください")
            lot_entry = 0
            lot_stop = 0
        _lot_raw = calc_lot_r(
            entry_price=lot_entry,
            stop_loss_price=lot_stop,
            max_r=lot_max_r,
            r_unit=lot_r_unit,
        )
        result = dict(_lot_raw)
        result['lot'] = (result['lot'] // 100) * 100
        st.session_state["lot_calc_result"] = result
        st.session_state["lot_calc_grade"] = lot_grade
        st.session_state["lot_calc_ticker"] = lot_ticker_input
        st.session_state["lot_calc_entry"] = lot_entry

        st.metric("ロット数", f"{result['lot']} 株（100株単位）")
        c1, c2, c3 = st.columns(3)
        c1.metric("リスク金額", f"¥{result['risk_amount']:,.0f}")
        c2.metric("1株あたり損切額", f"¥{result['loss_per_share']:,.0f}")
        c3.metric("ポジションサイズ", f"¥{result['position_size']:,.0f}")

    # --- ウォッチリストにロット追加 ---
    if st.session_state.get("lot_calc_result") and st.session_state.get("lot_calc_ticker"):
        _ticker = st.session_state["lot_calc_ticker"]
        _result = st.session_state["lot_calc_result"]
        _grade = st.session_state["lot_calc_grade"]
        _entry = st.session_state.get("lot_calc_entry", 0)

        matched = db.get_stocks_by_ticker(_ticker)
        if matched:
            latest = matched[0]
            lot_text = f"{_grade}級 / {_result['lot']}株 / IN:¥{_entry:,.0f} / リスク:¥{_result['risk_amount']:,.0f}"
            st.markdown("---")
            st.markdown(f"**{latest['name']}（{_ticker}）** のウォッチリスト（ID: {latest['id']}）にロット情報を追加")
            if st.button("ウォッチリストにロット追加", key="add_lot_to_wl"):
                existing_memo = latest.get("memo", "") or ""
                new_memo = f"{existing_memo}\n[ロット] {lot_text}".strip()
                db.update_stock(latest["id"], {
                    "grade": _grade,
                    "max_r": _result["max_r"],
                    "lot_strategy": lot_text,
                    "memo": new_memo,
                })
                st.success(f"{latest['name']} にロット情報を追加しました: {lot_text}")
                st.session_state.pop("lot_calc_result", None)
                st.session_state.pop("lot_calc_ticker", None)
                st.rerun()
        else:
            st.info(f"証券コード {_ticker} はウォッチリストに登録されていません。先にサイドバーから銘柄を追加してください。")

# --- タブ6: 期待値計算 ---
with tab6:
    st.subheader("トレード期待値計算")

    col1, col2, col3 = st.columns(3)
    with col1:
        ev_winrate = st.number_input("勝率（%）", value=50.0, min_value=0.0, max_value=100.0, step=1.0)
    with col2:
        ev_win = st.number_input("平均利益（円）", value=30000, step=1000)
    with col3:
        ev_loss = st.number_input("平均損失（円）", value=20000, step=1000)

    if st.button("計算", key="calc_ev"):
        result = calc_expected_value(
            win_rate=ev_winrate / 100,
            avg_win=ev_win,
            avg_loss=ev_loss,
        )
        c1, c2, c3 = st.columns(3)
        c1.metric("期待値 / トレード", f"¥{result['expected_value']:,.0f}")
        c2.metric("プロフィットファクター", f"{result['profit_factor']:.2f}")
        c3.metric("損益分岐勝率", f"{result['breakeven_winrate'] * 100:.1f}%")

        if result["expected_value"] > 0:
            st.success("期待値はプラスです。このルールを継続しましょう。")
        else:
            st.warning("期待値はマイナスです。ルールの見直しを検討してください。")

# --- タブ7: 適時開示 ---
with tab7:
    st.subheader("適時開示一覧（時価総額100億以下）")

    # データ取得ボタン
    disc_btn_c1, disc_btn_c2, _ = st.columns([1, 1, 2])
    with disc_btn_c1:
        if st.button("株探から取得", key="fetch_kabutan_disc", type="primary"):
            with st.spinner("株探から適時開示を取得中..."):
                try:
                    from data_fetch import fetch_kabutan_disclosures
                    new_items = fetch_kabutan_disclosures()
                    added = 0
                    for item in new_items:
                        result = db.add_disclosure(item)
                        if result is not None:
                            added += 1
                    st.success(f"株探: {len(new_items)}件取得、{added}件新規追加")
                except Exception as e:
                    st.error(f"株探取得エラー: {e}")
    with disc_btn_c2:
        if st.button("PRTimesから取得", key="fetch_prtimes_disc"):
            with st.spinner("PRTimesから取得中..."):
                try:
                    from data_fetch import fetch_prtimes_latest
                    new_items = fetch_prtimes_latest()
                    added = 0
                    for item in new_items:
                        result = db.add_disclosure(item)
                        if result is not None:
                            added += 1
                    st.success(f"PRTimes: {len(new_items)}件取得、{added}件新規追加")
                except Exception as e:
                    st.error(f"PRTimes取得エラー: {e}")

    # フィルタ
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        disc_date = st.date_input("日付フィルタ", value=today_jst(), key="disc_date")
    with fc2:
        disc_source = st.selectbox("ソース", ["すべて", "kabutan", "prtimes"], key="disc_source")
    with fc3:
        disc_cap_filter = st.number_input(
            "時価総額上限（億円）", value=100, min_value=1, step=10, key="disc_cap_filter"
        )

    source_filter = disc_source if disc_source != "すべて" else None
    disclosures = db.get_disclosures(source=source_filter, target_date=str(disc_date))

    # 時価総額フィルタ適用
    cap_filter_yen = disc_cap_filter * 100_000_000
    disclosures = [d for d in disclosures if d.get("market_cap") and d["market_cap"] <= cap_filter_yen]

    if disclosures:
        df_disc = pd.DataFrame(disclosures)
        disc_cols = {
            "id": "ID",
            "ticker": "コード",
            "company_name": "会社名",
            "market": "市場",
            "disclosure_type": "種別",
            "title": "タイトル",
            "disclosed_at": "開示日時",
            "market_cap": "時価総額",
            "source": "ソース",
            "notified": "通知済",
        }
        df_disc_show = df_disc[[c for c in disc_cols if c in df_disc.columns]].rename(columns=disc_cols)

        if "時価総額" in df_disc_show.columns:
            df_disc_show["時価総額"] = df_disc_show["時価総額"].apply(
                lambda x: f"{x / 100_000_000:.0f}億" if pd.notna(x) and x else ""
            )
        if "通知済" in df_disc_show.columns:
            df_disc_show["通知済"] = df_disc_show["通知済"].apply(lambda x: "✓" if x else "")

        st.dataframe(df_disc_show, use_container_width=True, hide_index=True)

        # ウォッチリストに追加
        with st.expander("ウォッチリストに追加"):
            add_disc_id = st.number_input("開示ID", min_value=1, step=1, key="add_disc_id")
            if st.button("ウォッチリストに追加", key="add_disc_to_wl"):
                target = next((d for d in disclosures if d["id"] == add_disc_id), None)
                if target:
                    stock_id = db.add_stock({
                        "date": str(today_jst()),
                        "name": target["company_name"],
                        "ticker": target["ticker"],
                        "market_cap": target.get("market_cap"),
                        "memo": f"適時開示: {target.get('title', '')}",
                    })
                    st.success(f"{target['company_name']}（{target['ticker']}）をウォッチリストに追加しました（ID: {stock_id}）")
                else:
                    st.error("指定されたIDの開示が見つかりません")

        st.caption(f"表示件数: {len(disclosures)}件")
    else:
        st.info("該当する適時開示はありません。上の「株探から取得」ボタンでデータを取得してください。")

# --- タブ8: 監視パネル ---
rss_interval = config.get("api", {}).get("update_interval", 60)

with tab8:
    st.subheader("リアルタイム監視パネル")

    # --- 環境チェック ---
    with st.expander("環境チェック", expanded=False):
        if st.button("環境チェック実行", key="env_check_btn"):
            env_c1, env_c2, env_c3 = st.columns(3)
            with env_c1:
                try:
                    import yfinance as _yf
                    st.success(f"yfinance: v{_yf.__version__}")
                except Exception:
                    st.error("yfinance: 未インストール")
            with env_c2:
                try:
                    from stock_api import test_connection as _tc
                    _ok, _msg = _tc()
                    if _ok:
                        st.success(f"API接続: {_msg}")
                    else:
                        st.error(f"API接続: {_msg}")
                except Exception:
                    st.error("API接続チェック失敗")
            with env_c3:
                _line_cfg = config.get("line", {})
                _has_token = bool(_line_cfg.get("channel_access_token", ""))
                try:
                    _secrets_line = st.secrets.get("line", {})
                    if _secrets_line.get("channel_access_token", ""):
                        _has_token = True
                except Exception:
                    pass
                if _has_token:
                    st.success("LINE: トークン設定済み")
                else:
                    st.error("LINE: トークン未設定（Secrets に line.channel_access_token を設定）")

            env_c4, = st.columns(1)
            with env_c4:
                try:
                    from cloud_storage import is_configured as _cs_ok
                    if _cs_ok():
                        st.success("GitHub backup: 設定済み（データ永続化ON）")
                    else:
                        st.warning("GitHub backup: 未設定 — Secrets に [github] token / repo を設定するとデータが永続化されます")
                except Exception:
                    st.error("cloud_storage 読み込み失敗")

        if st.button("LINE通知テスト", key="line_test_btn"):
            try:
                from notifier import send_line as _sl, get_last_line_status as _gls
                _test_ok = _sl("FUDO 監視パネル テスト通知")
                _status = _gls()
                if _test_ok:
                    st.success("LINE通知テスト成功")
                else:
                    st.error("LINE通知テスト失敗")
            except Exception:
                st.error("LINE通知モジュール読み込み失敗")

    # --- アラート ON/OFF トグル ---
    st.markdown("##### アラート設定")
    al_c1, al_c2, al_c3, al_c4 = st.columns(4)
    with al_c1:
        alert_screen = st.toggle(
            "スクリーニング通知",
            value=st.session_state.get("alert_screen", True),
            key="alert_screen",
            help="貸借 / 時価総額100億以下 / 出来高100万以上",
        )
    with al_c2:
        alert_surge = st.toggle(
            "急騰アラート",
            value=st.session_state.get("alert_surge", True),
            key="alert_surge",
            help="3分間+4%以上の急騰を検出",
        )
    with al_c3:
        alert_price = st.toggle(
            "価格アラート",
            value=st.session_state.get("alert_price", True),
            key="alert_price",
            help="指定株価到達 / 出来高急増",
        )
    with al_c4:
        alert_fushi = st.toggle(
            "節目アラート",
            value=st.session_state.get("alert_fushi", True),
            key="alert_fushi",
            help="登録節目の±0.5%圏内で通知",
        )

    st.markdown("---")

    monitor_input = st.text_area(
        "証券コードを入力（カンマ or 改行区切り）",
        placeholder="例: 6920, 3856\nまたは1行ずつ入力",
        height=100,
        key="monitor_tickers",
    )

    mc1, mc2 = st.columns([1, 3])
    with mc1:
        monitor_start = st.button("監視開始", key="monitor_start", type="primary")
    with mc2:
        monitor_stop = st.button("監視停止", key="monitor_stop")

    if monitor_start and monitor_input:
        raw_tickers = monitor_input.replace(",", "\n").replace("　", "\n").split("\n")
        parsed = [t.strip() for t in raw_tickers if t.strip().isdigit()]
        if parsed:
            st.session_state["monitor_active"] = True
            st.session_state["monitor_ticker_list"] = parsed
        else:
            st.warning("有効な証券コードが入力されていません。")

    if monitor_stop:
        st.session_state["monitor_active"] = False

    # --- ウォッチリストから自動入力 ---
    wl_stocks = db.get_stocks(str(today_jst()))
    if not wl_stocks:
        wl_stocks = db.get_stocks()
    if wl_stocks:
        wl_tickers = [f"{s['ticker']} ({s['name']})" for s in wl_stocks if s.get('ticker')]
        selected_wl = st.multiselect("ウォッチリストから選択", wl_tickers, key="monitor_wl_select")
        if selected_wl:
            auto_tickers = [t.split(" ")[0] for t in selected_wl]
            existing = monitor_input or ""
            if st.button("選択した銘柄を追加", key="add_wl_to_monitor"):
                combined = existing + ("\n" if existing else "") + "\n".join(auto_tickers)
                st.session_state["monitor_tickers"] = combined
                st.rerun()

    # --- リアルタイム自動更新フラグメント ---
    @st.fragment(run_every=timedelta(seconds=rss_interval))
    def _monitor_fragment():
      try:
        if not st.session_state.get("monitor_active"):
            st.info("証券コードを入力して「監視開始」を押してください。")
            return

        tickers = st.session_state.get("monitor_ticker_list", [])
        if not tickers:
            return

        now_jst = datetime.now(JST)
        st.caption(f"自動更新中（{rss_interval}秒間隔）　最終更新: {now_jst.strftime('%H:%M:%S')}")

        if get_rss_prices is None:
            st.error("rss_monitor モジュールの読み込みに失敗しています。ログを確認してください。")
            return

        try:
            prices = get_rss_prices(tickers)
        except Exception as e:
            st.error(f"データ取得エラー: {e}")
            import traceback
            st.code(traceback.format_exc())
            return

        if not prices:
            st.warning("株価データを取得できませんでした。市場時間外か、APIに問題がある可能性があります。")
            return

        price_map = {p["ticker"]: p for p in prices}

        # 3分間+4%急騰チェック → LINE通知
        if st.session_state.get("alert_surge", True) and check_surge_alerts:
            try:
                surge_hits = check_surge_alerts(prices)
                if surge_hits:
                    surge_names = ", ".join(f"{h['name']}（{h['ticker']}）" for h in surge_hits)
                    st.success(f"🚀 急騰検出 → LINE通知済: {surge_names}")
            except Exception as e:
                st.warning(f"急騰チェックエラー: {e}")

        # RSSスクリーニング（貸借/時価総額/出来高） → LINE通知
        if st.session_state.get("alert_screen", True):
            try:
                from rss_monitor import screen_and_notify
                screen_hits = screen_and_notify(prices)
                if screen_hits:
                    screen_names = ", ".join(f"{h['name']}（{h['ticker']}）" for h in screen_hits)
                    st.success(f"🔍 スクリーニングHIT → LINE通知済: {screen_names}")
            except Exception as e:
                st.warning(f"スクリーニングエラー: {e}")

        # 価格 / 出来高アラート
        if st.session_state.get("alert_price", True) and check_price_alerts:
            try:
                check_price_alerts(prices)
            except Exception as e:
                st.warning(f"価格アラートエラー: {e}")

        # 節目アラート
        if st.session_state.get("alert_fushi", True) and check_fushi_alerts:
            try:
                check_fushi_alerts(prices)
            except Exception as e:
                st.warning(f"節目アラートエラー: {e}")

        # LINE通知ステータス表示
        try:
            from notifier import get_last_line_status as _get_line_st
            _line_st = _get_line_st()
            if _line_st["ok"] is not None:
                if _line_st["ok"]:
                    st.caption(f"LINE: {_line_st['msg']}")
                else:
                    st.warning(f"LINE通知エラー: {_line_st['msg']}")
        except Exception:
            pass

        st.success(f"取得成功: {len(prices)}/{len(tickers)} 銘柄")

        for ticker in tickers:
            p = price_map.get(ticker)
            if not p:
                st.warning(f"{ticker}: データなし")
                continue

            with st.container():
                st.markdown("---")

                change = p.get("change", 0) or 0
                price_val = p.get("price", 0) or 0
                prev_price = price_val - change if price_val else 0
                change_pct = (change / prev_price * 100) if prev_price else 0

                if change > 0:
                    color = "red"
                    sign = "+"
                elif change < 0:
                    color = "green"
                    sign = ""
                else:
                    color = "gray"
                    sign = ""

                vol_man = (p.get("volume", 0) or 0) / 10_000

                st.markdown(
                    f"### {p.get('name', '')}（{ticker}）　"
                    f"現在値 **¥{price_val:,.0f}**　"
                    f"<span style='color:{color}; font-weight:bold'>"
                    f"{sign}{change:,.0f}円 / {sign}{change_pct:.2f}%</span>　"
                    f"出来高 {vol_man:,.0f}万株",
                    unsafe_allow_html=True,
                )

                board = get_rss_board(ticker)
                if board:
                    sell_list = board["sell"]
                    buy_list = board["buy"]

                    rows_html = []
                    for s in sell_list:
                        if s["price"] > 0:
                            rows_html.append(
                                f"<tr>"
                                f"<td style='text-align:right; color:#1e88e5'>{s['volume']:,}</td>"
                                f"<td style='text-align:center; font-weight:bold'>{s['price']:,.0f}</td>"
                                f"<td></td>"
                                f"</tr>"
                            )

                    for b in buy_list:
                        if b["price"] > 0:
                            rows_html.append(
                                f"<tr>"
                                f"<td></td>"
                                f"<td style='text-align:center; font-weight:bold'>{b['price']:,.0f}</td>"
                                f"<td style='text-align:right; color:#e53935'>{b['volume']:,}</td>"
                                f"</tr>"
                            )

                    if rows_html:
                        table_html = (
                            "<table style='width:400px; border-collapse:collapse; font-size:14px'>"
                            "<thead><tr>"
                            "<th style='text-align:right; padding:4px 8px; border-bottom:2px solid #ccc'>売数量</th>"
                            "<th style='text-align:center; padding:4px 8px; border-bottom:2px solid #ccc'>価格</th>"
                            "<th style='text-align:right; padding:4px 8px; border-bottom:2px solid #ccc'>買数量</th>"
                            "</tr></thead><tbody>"
                            + "\n".join(rows_html)
                            + "</tbody></table>"
                        )
                        st.markdown(table_html, unsafe_allow_html=True)
                    else:
                        st.caption("板データなし")
                else:
                    st.caption("板データなし（無料APIでは板情報を取得できません）")

      except Exception as _frag_err:
        import traceback as _tb
        st.error(f"監視パネルエラー: {type(_frag_err).__name__}: {_frag_err}")
        st.code(_tb.format_exc())

    _monitor_fragment()

# --- タブ9: Notion連携 ---
with tab9:
    st.subheader("Notion連携")

    notion_cfg = config.get("notion", {})
    has_notion_key = bool(notion_cfg.get("api_key", ""))
    has_notion_db = bool(notion_cfg.get("database_id", ""))
    try:
        _secrets_notion = st.secrets.get("notion", {})
        if _secrets_notion.get("api_key", ""):
            has_notion_key = True
        if _secrets_notion.get("database_id", ""):
            has_notion_db = True
    except Exception:
        pass

    if not has_notion_key or not has_notion_db:
        st.warning("Notion API キーまたはデータベースIDが未設定です。Streamlit Cloud の Secrets に以下を設定してください。")
        st.code("""[notion]
api_key = "your-notion-api-key"
database_id = "your-database-id\"""")
    else:
        st.success("Notion: 設定済み")

    st.markdown("---")

    # ウォッチリスト → Notion
    st.markdown("##### ウォッチリスト → Notion に同期")
    nc1, nc2 = st.columns(2)
    with nc1:
        notion_sync_date = st.date_input("対象日付", value=today_jst(), key="notion_sync_date")
    with nc2:
        st.write("")
        st.write("")
        notion_sync_all = st.checkbox("全日付を同期", key="notion_sync_all")

    if st.button("Notionに同期", key="notion_push_btn", type="primary"):
        if not has_notion_key or not has_notion_db:
            st.error("Notion API キーとデータベースIDを設定してください。")
        else:
            with st.spinner("Notion に同期中..."):
                try:
                    from notion_sync import push_to_notion
                    target_date = None if notion_sync_all else str(notion_sync_date)
                    sync_stocks = db.get_stocks(target_date)
                    if not sync_stocks:
                        st.info("同期対象の銘柄がありません。")
                    else:
                        success = 0
                        for stock in sync_stocks:
                            result = push_to_notion(stock)
                            if result:
                                success += 1
                        st.success(f"Notion同期完了: {success}/{len(sync_stocks)} 件")
                except Exception as e:
                    st.error(f"Notion同期エラー: {e}")

    # Notion → 確認
    st.markdown("---")
    st.markdown("##### Notion からデータ確認")
    if st.button("Notionから取得", key="notion_fetch_btn"):
        if not has_notion_key or not has_notion_db:
            st.error("Notion API キーとデータベースIDを設定してください。")
        else:
            with st.spinner("Notion からデータ取得中..."):
                try:
                    from notion_sync import fetch_from_notion
                    notion_data = fetch_from_notion()
                    if notion_data:
                        df_notion = pd.DataFrame(notion_data)
                        st.dataframe(df_notion, use_container_width=True, hide_index=True)
                        st.caption(f"取得件数: {len(notion_data)}件")
                    else:
                        st.info("Notionにデータがないか、取得に失敗しました。")
                except Exception as e:
                    st.error(f"Notion取得エラー: {e}")

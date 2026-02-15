"""FUDO - メインUI（Streamlit）"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta

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

st.set_page_config(page_title="FUDO", page_icon="📊", layout="wide")

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

        input_date = st.date_input("日付", value=date.today())
        input_market_cap = st.slider("時価総額（億円）", min_value=0, max_value=1000, value=0, step=1)
        input_margin = st.slider("信用買残（%）", min_value=0.0, max_value=100.0, value=0.0, step=0.1)
        input_fushi = st.text_input("節目（例: 1500, 1450）")
        input_pts = st.slider("PTS出来高", min_value=0, max_value=1000000, value=0, step=100)
        input_disclosure = st.number_input("日々公表カウント", min_value=0, step=1)
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
            "memo": input_memo,
        })
        st.success(f"追加しました（ID: {stock_id}、{lot_text}）")
        st.rerun()

# ===== メインエリア =====
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "📋 ウォッチリスト",
    "📝 トレード記録",
    "📊 エントリー分析",
    "🔬 統計",
    "🧮 ロット計算",
    "📈 期待値計算",
    "📢 適時開示",
    "📡 監視パネル",
])

# --- タブ1: ウォッチリスト ---
with tab1:
    col_date, col_refresh = st.columns([3, 1])
    with col_date:
        filter_date = st.date_input("日付フィルタ", value=date.today(), key="filter_date")
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
            "daily_disclosure_count": "日々公表",
            "hiduke_position_good": "日足位置", "teii_or_taishaku": "低位/貸借",
            "meigara_quality": "銘柄質", "grade": "級",
            "max_r": "最大R", "lot_strategy": "ロット戦略", "memo": "メモ",
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
            t_date = st.date_input("日付", value=date.today(), key="t_date")
            t_name = st.text_input("銘柄名", key="t_name")
            t_ticker = st.text_input("証券コード", key="t_ticker")
        with tc2:
            t_grade = st.selectbox("級", ["SS", "S", "A"], key="t_grade")
            t_entry_type = st.selectbox("エントリー分類", entry_types, key="t_entry_type")
            t_quality = st.selectbox("銘柄質", quality_options, key="t_quality")
            t_lot = st.number_input("ロット（株数）", min_value=0, step=100, key="t_lot")
        with tc3:
            t_entry_price = st.number_input("エントリー価格", min_value=0, max_value=100000, value=0, step=1, key="t_entry_price")
            t_exit_price = st.number_input("手仕舞い価格", min_value=0, max_value=100000, value=0, step=1, key="t_exit_price")
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

        t_memo = st.text_area("メモ", height=68, key="t_memo")
        t_submitted = st.form_submit_button("トレード記録を保存", use_container_width=True)

    if t_submitted and t_name and t_ticker:
        pnl = (t_exit_price - t_entry_price) * t_lot if t_entry_price and t_exit_price and t_lot else 0
        trade_id = db.add_trade({
            "date": str(t_date),
            "name": t_name,
            "ticker": t_ticker,
            "grade": t_grade,
            "entry_type": t_entry_type,
            "entry_price": t_entry_price,
            "exit_price": t_exit_price,
            "lot": t_lot,
            "pnl": pnl,
            "result": t_result,
            "stop_osaedama": 1 if t_stop1 else 0,
            "stop_itakyushu": 1 if t_stop2 else 0,
            "stop_itakieru": 1 if t_stop3 else 0,
            "stop_fushi_noforce": 1 if t_stop4 else 0,
            "meigara_quality": t_quality,
            "memo": t_memo,
        })
        pnl_text = f"+¥{pnl:,.0f}" if pnl >= 0 else f"-¥{abs(pnl):,.0f}"
        st.success(f"記録しました（ID: {trade_id}、損益: {pnl_text}）")
        st.rerun()

    # トレード一覧表示
    st.markdown("---")
    trades = db.get_trades()
    if trades:
        df_t = pd.DataFrame(trades)
        show_cols = {
            "id": "ID", "date": "日付", "name": "銘柄名", "ticker": "コード",
            "grade": "級", "entry_type": "分類", "meigara_quality": "銘柄質",
            "entry_price": "IN", "exit_price": "OUT",
            "lot": "ロット", "pnl": "損益", "result": "結果",
            "stop_osaedama": "抑え玉", "stop_itakyushu": "板吸収",
            "stop_itakieru": "板消え", "stop_fushi_noforce": "勢いなし",
            "memo": "メモ",
        }
        df_show = df_t[[c for c in show_cols if c in df_t.columns]].rename(columns=show_cols)

        # チェックボックス列を○×表示
        for col in ["抑え玉", "板吸収", "板消え", "勢いなし"]:
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
        lot_entry = st.number_input("エントリー価格（円）", min_value=0, max_value=100000, value=1000, step=1, key="lot_entry")
        lot_stop = st.number_input("損切り価格（円）", min_value=0, max_value=100000, value=950, step=1, key="lot_stop")

    if st.button("計算", key="calc_lot"):
        result = calc_lot_r(
            entry_price=lot_entry,
            stop_loss_price=lot_stop,
            max_r=lot_max_r,
            r_unit=lot_r_unit,
        )
        st.metric("ロット数", f"{result['lot']} 株")
        c1, c2, c3 = st.columns(3)
        c1.metric("リスク金額", f"¥{result['risk_amount']:,.0f}")
        c2.metric("1株あたり損切額", f"¥{result['loss_per_share']:,.0f}")
        c3.metric("ポジションサイズ", f"¥{result['position_size']:,.0f}")

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

    # フィルタ
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        disc_date = st.date_input("日付フィルタ", value=date.today(), key="disc_date")
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
                        "date": str(date.today()),
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
        st.info("該当する適時開示はありません。")

# --- タブ8: 監視パネル ---
rss_interval = config.get("api", {}).get("update_interval", 60)

with tab8:
    st.subheader("リアルタイム監視パネル")

    # --- 環境チェック ---
    with st.expander("環境チェック", expanded=False):
        env_c1, env_c2 = st.columns(2)
        with env_c1:
            try:
                import yfinance as _yf
                st.success(f"yfinance: v{_yf.__version__}")
            except ImportError:
                st.error("yfinance: 未インストール")
        with env_c2:
            from stock_api import test_connection
            ok, msg = test_connection()
            if ok:
                st.success(f"API接続: {msg}")
            else:
                st.error(f"API接続: {msg}")

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

    # --- リアルタイム自動更新フラグメント ---
    @st.fragment(run_every=timedelta(seconds=rss_interval))
    def _monitor_fragment():
        if not st.session_state.get("monitor_active"):
            st.info("証券コードを入力して「監視開始」を押してください。")
            return

        tickers = st.session_state.get("monitor_ticker_list", [])
        if not tickers:
            return

        from datetime import datetime as _dt
        st.caption(f"自動更新中（{rss_interval}秒間隔）　最終更新: {_dt.now().strftime('%H:%M:%S')}")

        prices = get_rss_prices(tickers)
        price_map = {p["ticker"]: p for p in prices}

        # 3分間+4%急騰チェック → LINE通知
        if st.session_state.get("alert_surge", True):
            surge_hits = check_surge_alerts(prices)
            if surge_hits:
                surge_names = ", ".join(f"{h['name']}（{h['ticker']}）" for h in surge_hits)
                st.success(f"🚀 急騰検出 → LINE通知済: {surge_names}")

        # RSSスクリーニング（貸借/時価総額/出来高） → LINE通知
        if st.session_state.get("alert_screen", True):
            from rss_monitor import screen_and_notify
            screen_hits = screen_and_notify(prices)
            if screen_hits:
                screen_names = ", ".join(f"{h['name']}（{h['ticker']}）" for h in screen_hits)
                st.success(f"🔍 スクリーニングHIT → LINE通知済: {screen_names}")

        # 価格 / 出来高アラート
        if st.session_state.get("alert_price", True):
            check_price_alerts(prices)

        # 節目アラート
        if st.session_state.get("alert_fushi", True):
            check_fushi_alerts(prices)

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

    _monitor_fragment()

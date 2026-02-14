_date=end, interval=selected_tf)
            if df is not None and not df.empty:
                df = calculate_all_indicators(df)
                ind1, vol1 = calculate_simplified_scores(df)
                ind2, vol2 = calculate_original_scores(df)
                latest = df.iloc[-1]
                prev = df.iloc[-2] if len(df) > 1 else latest
                price_change_pct = ((latest['Close'] - prev['Close']) / prev['Close']) * 100 if len(df) > 1 else 0
                sentiment_text, sentiment_emoji, sentiment_class, confidence = calculate_sentiment(
                    ind2, vol2, latest['RSI'], latest['Diff'], price_change_pct
                )
                st.subheader(f"📈 {stock} - {TIMEFRAMES[selected_tf]['label']}")
                st.markdown(f"""
                <div class="{sentiment_class}">
                    {sentiment_emoji} SENTIMENT: {sentiment_text}
                    <br>
                    <span style="font-size: 1rem;">Confidence: {confidence:.0f}%</span>
                </div>
                """, unsafe_allow_html=True)
                col1, col2, col3, col4 = st.columns(4)
                ch = latest['Close'] - prev['Close']
                with col1:
                    st.metric("Price", f"₺{latest['Close']:.2f}", f"{ch:.2f} ({price_change_pct:.2f}%)")
                with col2:
                    st.metric("Volume", f"{latest['Volume']:,.0f}")
                with col3:
                    st.metric("RSI", f"{latest['RSI']:.2f}")
                with col4:
                    st.metric("MACD", f"{latest['MACD']:.4f}")
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("#### Score 2 (Original) ⭐")
                    c1, c2 = st.columns(2)
                    with c1:
                        st.plotly_chart(create_gauge(ind2, "Indicator 2", 10), use_container_width=True)
                    with c2:
                        st.metric("Volume 2", f"{vol2:.2f}")
                        if vol2 > 0.7:
                            st.success("✅ Above 0.7")
                        else:
                            st.warning("⚠️ Below 0.7")
                with col2:
                    st.markdown("#### Score 1 (Simplified)")
                    c1, c2 = st.columns(2)
                    with c1:
                        st.plotly_chart(create_gauge(ind1, "Indicator 1"), use_container_width=True)
                    with c2:
                        st.plotly_chart(create_gauge(vol1, "Volume 1"), use_container_width=True)
                if ind2 >= 3 and vol2 > 0.7:
                    st.markdown('<div class="chosen-stock"><h3>⭐ CHOSEN STOCK! ⭐</h3></div>', unsafe_allow_html=True)
                st.plotly_chart(create_candlestick(df, stock), use_container_width=True)
            else:
                st.error(f"❌ No data available for {stock}")
        else:
            st.subheader("🔍 Chosen Stocks")
            if selected_tf in st.session_state.chosen_stocks and st.session_state.chosen_stocks[selected_tf]:
                results = st.session_state.chosen_stocks[selected_tf]
                df_c = pd.DataFrame(results).sort_values('indicator_score_2', ascending=False)
                st.dataframe(df_c, use_container_width=True)
                cols = st.columns(3)
                for idx, s in enumerate(df_c.to_dict('records')):
                    with cols[idx % 3]:
                        st.markdown(f"""
                        <div class="chosen-stock">
                            <h4>{s['symbol']}</h4>
                            <p><b>Indicator:</b> {s['indicator_score_2']}</p>
                            <p><b>Volume:</b> {s['volume_score_2']}</p>
                        </div>
                        """, unsafe_allow_html=True)
            else:
                st.info("Click 'Run Screener'")
    except Exception as e:
        st.error(f"An error occurred: {str(e)}")
        st.info("Please refresh the page and try again.")

if __name__ == "__main__":
    main()

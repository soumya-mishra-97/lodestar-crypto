# Worked example: Polygon (POL)

This is an unedited export (`GET /api/v1/reports/{id}/export.md`) of the report produced by `make up` for the sample coin **Polygon (POL)**, in **demo mode**, so every figure is synthetic. With a CoinGecko key the same pipeline runs on live data; with an Anthropic key, Claude chooses the analysts' tools and writes the claims, and the verifier checks them exactly as it checks this deterministic draft.

Reproduce it with `make run-pol` (inline) or by opening POL on the Overview.

---

## POL (ex-MATIC) (POL) · Lodestar report

_Generated 2026-11-03 14:35 UTC · on-demand · status: Pending approval · data: demo · writer: deterministic · pipeline 2026.11.2_

DEMO DATA: prices and metrics in this report are synthetic, not real market data.

- [INTERP] POL (ex-MATIC): short-term signals are unfavorable with moderate risk; long-term signals are unfavorable with high risk. (ASM-02, RSK-05, ASM-05, RSK-07)

## Assessments

| Horizon | Stance | Signal score | Risk level | Risk score | Confidence |
|---|---|---|---|---|---|
| Short-term | unfavorable | 25/100 | moderate | 32/100 | 100% |
| Long-term | unfavorable | 28/100 | high | 51/100 | 100% |

## Short term (days to four weeks)

### Thesis

- [CALC] The short-term signal score is 25 of 100 (unfavorable). (ASM-01, ASM-02)
- [CALC] The latest close of $0.0912 is below the 50-day average of $0.1115. (DAT-02, TEC-01)
- [CALC] The 14-day RSI is 40.4. (TEC-02)
- [CALC] Realised 30-day volatility is 125.7% annualised. (TEC-13)
- [INTERP] MACD histogram is negative. (TEC-03)

### Risks

- [CALC] Short-term risk is moderate (score 32 of 100), driven mainly by volatility and liquidity. (RSK-04, RSK-05)
- [INTERP] Price is below its 20-day average. (DAT-02, TEC-08)
- [INTERP] Price is below its 50-day average. (DAT-02, TEC-01)

### What to watch

- [SCENARIO] If price closes below the 30-day low of $0.08655, the short-term picture would weaken. (TEC-15)
- [SCENARIO] If price holds above the 30-day high of $0.1228, short-term momentum would strengthen. (TEC-16)
- [FACT] The market-wide Fear & Greed Index reads 41 (Fear). (DAT-25, DAT-26)
- [CALC] 3 recent headlines mention POL (ex-MATIC); they are unverified context, not evidence for figures. (SEN-01, NWS-1, NWS-2, NWS-3)

### Risk factors

| Factor | Points | Detail |
|---|---|---|
| volatility | 22 | 30-day annualised volatility |
| liquidity | 10 | Order-book depth within 2% |

## Long term (six months or more)

### Thesis

- [CALC] The long-term signal score is 28 of 100 (unfavorable). (ASM-04, ASM-05)
- [CALC] Price is below its 200-day average of $0.1325, the long-term trend line. (DAT-02, TEC-09)
- [FACT] Market capitalisation is $948.48M, rank 48 by size. (DAT-03, DAT-06)
- [CALC] 99.3% of total supply is circulating. (FUN-01)
- [CALC] Daily volume equals 3.5% of market capitalisation. (FUN-03)
- [FACT] Total value locked in the ecosystem is $1.05B. (DAT-27)
- [INTERP] Top-100 asset by market capitalisation. (DAT-06)
- [INTERP] Nearly all supply already circulates. (FUN-01)
- [INTERP] No hard supply cap (inflationary design). (DAT-16)

### Risks

- [CALC] Long-term risk is high (score 51 of 100), driven mainly by drawdown and volatility. (RSK-06, RSK-07)
- [INTERP] One-year return is negative. (DAT-10)
- [INTERP] Price is below its 200-day average. (DAT-02, TEC-09)
- [INTERP] Trading far below its all-time high. (DAT-12)

### What to watch

- [SCENARIO] If price sustains a move across the 200-day average of $0.1325, the long-term trend signal would change direction. (TEC-09)

### Risk factors

| Factor | Points | Detail |
|---|---|---|
| volatility | 11 | 30-day annualised volatility |
| liquidity | 10 | Order-book depth within 2% |
| drawdown | 20 | Worst one-year peak-to-trough decline |
| size | 10 | Market capitalisation |

## Your portfolio

- [CALC] You hold 42,000 POL worth $3,830.40, 5.7% of your tracked portfolio. (PF-04, PF-05, PF-06)
- [CALC] Unrealised P&L on this position is -70.6% against your recorded cost basis. (PF-07)

## Data quality

- [CALC] Independent price sources agree; the largest deviation from their median is 0.1%. (DAT-29, DAT-30)
- [FACT] Demo-exchange last traded at $0.09131. (DAT-21)
- [FACT] The demo-aggregator aggregated price is $0.09113. (DAT-24)

## Assumptions and uncertainties

- [ASSUMPTION] Scores are rule-based summaries of past and current data; they do not predict future prices.
- [ASSUMPTION] Headlines and prediction-market questions are unverified third-party text, used as context only.

## Evidence cited (39 of 77 items)

| ID | Metric | Value | Kind | Source |
|---|---|---|---|---|
| DAT-02 | Latest daily close (USD) | $0.0912 | observation | demo |
| DAT-03 | Market capitalisation (USD) | $948,480,000.00 | observation | demo |
| DAT-06 | Market cap rank | 48 | observation | demo |
| DAT-10 | 1-year price change (%) | -81.92% | observation | demo |
| DAT-12 | Distance from all-time high (%) | -96.29% | observation | demo |
| DAT-16 | Max supply (tokens) | uncapped | observation | demo |
| DAT-21 | demo-exchange last price (POLUSD) | $0.09131 | observation | demo-exchange |
| DAT-24 | demo-aggregator aggregated price (USD) | $0.09113 | observation | demo-aggregator |
| DAT-25 | Crypto Fear & Greed Index (0-100) | 41 | observation | alternative.me |
| DAT-26 | Fear & Greed classification | Fear | observation | alternative.me |
| DAT-27 | Polygon total value locked (USD) | $1,050,000,000.00 | observation | defillama |
| DAT-29 | Price agreement across sources | consistent | calculation | lodestar |
| DAT-30 | Largest price deviation from the cross-source median (tolerance 1.5%) | 0.12% | calculation | lodestar |
| NWS-1 | Headline · demo.news | [Demo] POL core developers publish a quarterly roadmap update | text | demo.news |
| NWS-2 | Headline · demo.news | [Demo] Exchange flows for POL shift as traders rotate across large caps | text | demo.news |
| NWS-3 | Headline · demo.news | [Demo] Analysts debate POL network activity after recent volatility | text | demo.news |
| FUN-01 | Circulating / total supply (%) | 99.33% | calculation | lodestar |
| FUN-03 | 24h volume / market cap (%) | 3.53% | calculation | lodestar |
| RSK-04 | Short-term risk score (0-100) | 32 | calculation | lodestar |
| RSK-05 | Short-term risk level | moderate | calculation | lodestar |
| RSK-06 | Long-term risk score (0-100) | 51 | calculation | lodestar |
| RSK-07 | Long-term risk level | high | calculation | lodestar |
| SEN-01 | Relevant headlines found | 3 | calculation | lodestar |
| TEC-01 | 50-day simple moving average (USD) | $0.1115 | calculation | lodestar |
| TEC-02 | RSI (14-day) | 40.43 | calculation | lodestar |
| TEC-03 | MACD histogram (12/26/9) | $-0.0007602 | calculation | lodestar |
| TEC-08 | 20-day simple moving average (USD) | $0.1037 | calculation | lodestar |
| TEC-09 | 200-day simple moving average (USD) | $0.1325 | calculation | lodestar |
| TEC-13 | 30-day annualised volatility (%) | 125.66% | calculation | lodestar |
| TEC-15 | 30-day low (USD) | $0.08655 | calculation | lodestar |
| TEC-16 | 30-day high (USD) | $0.1228 | calculation | lodestar |
| ASM-01 | Short-term signal score (0-100) | 25 | calculation | lodestar |
| ASM-02 | Short-term stance | unfavorable | calculation | lodestar |
| ASM-04 | Long-term signal score (0-100) | 28 | calculation | lodestar |
| ASM-05 | Long-term stance | unfavorable | calculation | lodestar |
| PF-04 | POL held (tokens) | 42,000 | observation | portfolio |
| PF-05 | Value of your POL (USD) | $3,830.40 | calculation | lodestar |
| PF-06 | POL share of tracked portfolio (%) | 5.74% | calculation | lodestar |
| PF-07 | Unrealised P&L on POL vs cost basis (%) | -70.58% | calculation | lodestar |

_Verification: passed · 34 claims checked · 0 repair loop(s)_

## Disclaimer

Lodestar is a read-only research tool, not financial advice. Scores and risk levels are rule-based summaries of historical and current data; they are not predictions, guarantees or price targets. Crypto assets are highly volatile and you can lose some or all of the money you invest. Verify independently and consider your own circumstances before making any decision.

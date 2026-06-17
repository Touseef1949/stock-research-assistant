# Institutional-Style PDF Report Spec

## Goal
Restyle the Stock Research Assistant PDF report to match the institutional sample pack at `/Users/touseefshaik/Documents/institutional_financial_reports_full_pack.zip`.

## Current vs Proposed

| Aspect | Current Report | Proposed (Institutional) |
|--------|---------------|--------------------------|
| Cover | Dark gradient, title + verdict text | Clean brand bar, company name, report type, verdict panel with BUY/SELL/HOLD, target price, upside, horizon |
| Opening | Scorecard table then executive summary | Decision-first "Executive Investment View" with one-line verdict and key arguments |
| Tables | Flat key-value lists | Professional financial tables (header row, alternating fills, right-aligned numbers) |
| Structure | Section dump | Narrative sections: Executive View → Business Model → Forecast Snapshot → Valuation & Scenarios → Risks & Monitoring Dashboard → Catalyst Calendar → Governance → Disclaimer |
| Visuals | Basic headings | KPI boxes, scenario tables, risk dashboards, divider lines, page footers |
| Disclaimer | Single paragraph | Institutional notice block |

## Report Sections to Build

1. **Cover Page**
   - Brand bar: "Stock Research Assistant | AI App Factory"
   - Report type: "EQUITY RESEARCH REPORT"
   - Company name, ticker, exchange
   - Verdict panel: Verdict (BUY/SELL/HOLD), Target Price, Upside %, Time Horizon
   - Date and disclaimer microcopy

2. **Executive Investment View**
   - One-line thesis
   - Verdict bar: stance, base-case fair value, upside %, risk rating
   - Key investment arguments (4 bullets)
   - Decision grid: Question | Answer | Evidence needed

2. **Company and Market Architecture**
   - Business model map table: Revenue stream | Driver | Quality marker | Diligence concern
   - Interpretation paragraph
   - Market diligence checklist

3. **Forecast Model Snapshot**
   - Financial summary table: Revenue, YoY growth, EBITDA, EBITDA margin, PAT, OPM, ROE, Debt/Equity over available years
   - Model stance paragraph

4. **Quality of Earnings / Financial Health Lenses**
   - Table: Lens | Green flag | Yellow flag | Red flag
   - Use computed risk flags + financial trends

5. **Valuation and Scenarios**
   - Bull/Base/Bear scenario table: Probability, Revenue CAGR, Target EBITDA margin, Implied value, Thesis condition
   - Valuation method mix table: Method | Weight | Core assumption | Institutional caveat
   - Show fair value range and upside/downside

6. **Risks, Catalysts, and Monitoring Dashboard**
   - Risk dashboard table: Signal | Monitor | Target zone | Action if breached
   - Catalyst calendar table: Timing | Catalyst | Expected thesis impact
   - List top risk flags

7. **Governance**
   - Promoter holding, pledge, FII/DII, governance score
   - Governance flags

8. **Disclaimer / Important Notice**
   - Institutional disclaimer block

## Files to Modify
- `deep_research/report.py` — rewrite `build_enhanced_pdf` and helpers
- Keep `_fallback_text_report` for failure mode
- Add safe helpers for tables, KPI boxes, section headers
- Maintain Unicode-safe text function `_safe_text`

## Design Palette (Ali Abbaal Light / Institutional)
- Background: white `#FFFFFF`
- Text: near-black `#1A1A1A`
- Accent green: `#1DB954`
- Borders/dividers: `#E8E8E8`
- Panels: `#F5F5F5`
- Header row: `#0F172A` (navy) with white text
- No heavy color coding; use thin green rules for emphasis

## Implementation Notes
- Use `fpdf2` only
- All text through `_safe_text` with latin-1 encoding fallback
- Tables use `_render_table` helper with header row styling and alternating fills
- Page footer on every page: "Stock Research Assistant | AI App Factory | Page N"
- Page margins: 16mm
- Font: Helvetica family

## Testing Checklist
- [ ] `python3 -m py_compile deep_research/report.py`
- [ ] `python3 -m pytest tests/ -q` passes
- [ ] Generate a sample PDF with mock data and visually verify cover + all sections
- [ ] Verify no encoding errors for ₹, —, em-dashes, smart quotes
- [ ] Confirm fallback text report still works

## Constraints
- Do not change payment, auth, scoring, or deep research modules
- Do not add new dependencies
- Preserve existing public function signature `build_enhanced_pdf(data, quick_result, deep_result)`

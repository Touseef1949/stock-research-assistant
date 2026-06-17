# UI Cleanup Spec: Stock Research Assistant Landing Page

## Goal
Reduce duplication and visual clutter on the landing page so the app feels like a polished product rather than a Streamlit MVP. Target taste score ≥ 8.5/10.

## Current vs Proposed

| Issue | Current | Proposed |
|-------|---------|----------|
| Duplicate ticker action | Sidebar has "Run Report from Sidebar" button; main hero has "Generate Research Report" | Only the hero primary CTA triggers analysis. Sidebar input is setup only. |
| Duplicate dimension chips | Hero header shows Fundamentals/Technicals/Sentiment/Risk chips; sample report repeats them | Remove chips from hero header. Keep sample report preview but without section pills. |
| Duplicate proof pills | Hero action strip lists Verdict-driven/Scorecards/Technicals chart/PDF export; these echo the agent dimensions | Remove proof row from hero action strip. Single headline + CTA is enough. |
| Pricing banner competes with CTA | Green banner "FREE TIER: 5 REPORTS · PRO: 100 REPORTS AT ₹199/MO" sits directly above the green primary button | Move pricing to a muted sub-line below the CTA or to the sidebar help card only. |
| Sidebar order | Sign out sits between plan status and Research Setup; user/plan info shown in both sidebar and footer | Move Sign out to bottom of sidebar. Remove plan/status from sidebar; keep only in footer. |
| Sample report clutter | "Try: INFY / RELIANCE / SBIN" line duplicates quick-pick grid | Remove the line. Quick-pick grid already provides the same function. |

## Files to Modify
1. `ui.py`
   - `page_header()`: remove `<div class="hero-chip-label">Analysis dimensions</div>` and the entire `hero-chip-row`
   - `sample_report_preview()`: remove `sample-report-sections` pill block and `sample-report-try` line
2. `app.py`
   - `render_sidebar()`: remove sidebar analyze button; move sign-out to bottom; remove plan usage duplication from sidebar
   - `render_hero_action()`: remove proof row; demote pricing banner to muted sub-line; keep single primary CTA
   - `main()`: remove `analyze` from sidebar return and hero analysis condition; only `hero_analyze` triggers report

## Design Constraints
- Preserve light theme Ali Abdaal palette (#FFFFFF bg, #1A1A1A text, #1DB954 accent, #E8E8E8 borders, #F5F5F5 panels)
- Do not change payment logic, scoring, or deep research modules
- Keep `render_footer()` as the single place for user/plan/reports info
- Maintain accessibility labels

## Testing Checklist
- [ ] `python3 -m py_compile app.py ui.py`
- [ ] `python3 -m pytest tests/ -q` passes
- [ ] Webwright/Playwright smoke: app loads, one primary CTA, sidebar has Access above Research Setup, no duplicate chips
- [ ] Vision taste audit ≥ 8.5/10

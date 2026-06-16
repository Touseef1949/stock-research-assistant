# Stock Research Assistant — UI Regression Suite

## Critical Points

### Flow 1: App Loads
- [ ] CP1: App loads at HF Spaces URL, title = "Stock Research Assistant"
- [ ] CP2: Sidebar renders with "Access", "Research setup", quick-pick buttons
- [ ] CP3: Main area shows hero section with "Generate" button

### Flow 2: Generate Report
- [ ] CP4: SBIN is pre-filled in ticker input
- [ ] CP5: Clicking "Generate SBIN Research Report" starts analysis
- [ ] CP6: Progress indicators appear (Running..., progress bar, step labels)
- [ ] CP7: Report completes with verdict visible (BUY/HOLD/SELL/AVOID)
- [ ] CP8: Score cards for all 4 dimensions render

### Flow 3: PDF Download
- [ ] CP9: PDF download button appears after report generation
- [ ] CP10: Downloaded PDF is valid (%PDF- header, >1KB)

### Flow 4: Deep Research Tab
- [ ] CP11: Deep Research tab/content is accessible
- [ ] CP12: Deep research result renders without errors

### Flow 5: Quick Pick
- [ ] CP13: Clicking RELIANCE quick-pick updates ticker input to RELIANCE
- [ ] CP14: Report generates for RELIANCE with verdict

### Flow 6: Theme Toggle
- [ ] CP15: Light theme is default
- [ ] CP16: Clicking theme toggle switches to dark theme

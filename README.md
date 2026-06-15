# Stock Research Assistant

AI-assisted NSE stock research with fundamentals, technicals, sentiment, risk, and a coordinated verdict.

## Running locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Environment variables

The app expects these secrets via Hugging Face Space secrets:

- `DEEPSEEK_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `RAZORPAY_KEY_ID`
- `RAZORPAY_KEY_SECRET`

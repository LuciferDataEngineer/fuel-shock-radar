# Synthetic FuelWatch-shaped fixtures

Every trading name, address and observation in these files is fictional test data. No row is a real fuel price or retailer record. The headers and DD/MM/YYYY date format follow Western Australia's public FuelWatch monthly CSV contract. Prices are cents per litre.

- `september_2026.csv`: all 30 September dates, with 36 observations at four fictional sites. Example Anchor is present every day at 175.0 c/L. Alpha moves 150.0 → 160.0 between September 1 and 2; Bravo moves 200.0 → 190.0. Entrant appears only September 2 at 300.0. The matched-site mean change is exactly 0.0 despite a change in the cross-sectional price distribution. Alpha's next observation is September 4, so it must not count as a September 4 day-on-day change.
- `august_2026.csv`: all 31 August dates at one fictional site, 199.9 c/L. Used to prove that replacing September leaves August unchanged.

Tests use `as_of="2026-10-30"` so both months are completed and validation remains reproducible.

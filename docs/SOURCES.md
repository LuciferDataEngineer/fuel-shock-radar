# Sources and interpretation

Source access checked **30 October 2026, Australia/Melbourne**. The project analyses completed monthly retail-price archives. It does not ingest crude-oil prices, wholesale prices, transaction volumes, or real-time pump readings.

## Source register

| Item | Reference |
| --- | --- |
| Dataset | FuelWatch Historic Fuel Prices |
| Publisher recorded in the WA catalog | Department of Energy, Mines, Industry Regulation and Safety |
| Data custodian | FuelWatch |
| Primary dataset catalog | <https://catalogue.data.wa.gov.au/dataset/fuelwatch-historic-fuel-prices> |
| Machine-readable catalog metadata | <https://catalogue.data.wa.gov.au/api/3/action/package_show?id=fuelwatch-historic-fuel-prices> |
| Publisher's archive landing page | <https://www.fuelwatch.wa.gov.au/retail/historic> |
| September CSV used for validation | <https://warsydprdstafuelwatch.blob.core.windows.net/historical-reports/FuelWatchRetail-09-2026.csv> |
| License stated by the primary catalog | [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/) |
| Credential requirement observed | No account, API key, or payment required for the catalog API or CSV download |

The primary catalog describes daily retailer-reported prices dating back to January 2001. It says the current monthly file is extended daily with the previous day's observations. Accordingly, a historical file's latest date is not a claim about today's price. The catalog API returned `license_id: cc-by` and `license_title: Creative Commons Attribution 4.0`. [WA dataset record](https://catalogue.data.wa.gov.au/dataset/fuelwatch-historic-fuel-prices)

### Download provenance and access limits

The CSV URL pattern was discovered in the public [FuelWatchHistory archive client](https://github.com/josh2893/FuelWatchHistory/blob/main/app/archive.py), then the September and October files were fetched directly from the named storage endpoint. No third-party application code or transformed dataset was copied. The primary catalog links to FuelWatch's archive page but does not itself enumerate these storage URLs.

During verification, the archive page exposed a JavaScript loading screen through the research browser and returned HTTP 403 to the local HTTP client. The available browser-control service had no browser sessions. Consequently, the live page-to-storage link could not be independently inspected in this run; the Azure account's ownership is not established by its name alone. The actual download URL and checksum remain explicit so the provenance can be audited.

The separate RSS endpoint, `https://www.fuelwatch.wa.gov.au/fuelwatch/fuelWatchRSS`, also returned HTTP 403 to the local client. RSS was not used as a data source. Its reuse terms were not verified, and the historical dataset's license should not automatically be applied to every other FuelWatch interface. No access-control workaround was attempted.

### Verified September snapshot

| Property | Observed value |
| --- | --- |
| HTTP result | 200 |
| Source file | `FuelWatchRetail-09-2026.csv` |
| Bytes | 10,792,061 |
| Data records, excluding header | 101,303 |
| Source dates | 1–30 September 2026; all 30 dates represented |
| HTTP Last-Modified | `Wed, 30 Sep 2026 16:30:02 GMT` |
| SHA-256 | `957ccd0afb20552f0b6ff255c4913963e1dac89208f1792f1b13426d5b360e5b` |

The October file was checked only to establish freshness behavior: it returned 98,008 records covering 1–29 October. It was incomplete as a calendar month on the access date and is outside this version's completed-month ingestion contract. These counts describe the responses checked, not permanent expectations for files that a publisher may correct.

## Field contract and grain

The checked CSV header is:

```text
PUBLISH_DATE,TRADING_NAME,BRAND_DESCRIPTION,PRODUCT_DESCRIPTION,PRODUCT_PRICE,ADDRESS,LOCATION,POSTCODE,AREA_DESCRIPTION,REGION_DESCRIPTION
```

| Field | Interpretation |
| --- | --- |
| `PUBLISH_DATE` | Source date in `DD/MM/YYYY`; preserve separately from download time |
| `TRADING_NAME` | Retailer's reported trading name |
| `BRAND_DESCRIPTION` | Reported brand, not a corporate-ownership mapping |
| `PRODUCT_DESCRIPTION` | Product label; keep different fuels separate |
| `PRODUCT_PRICE` | Reported price in Australian cents per litre |
| `ADDRESS`, `LOCATION`, `POSTCODE` | Reported address, locality, and postal code |
| `AREA_DESCRIPTION`, `REGION_DESCRIPTION` | Publisher's geography labels; not inferred statistical boundaries |

September contains `ULP`, `PULP`, `98 RON`, `Diesel`, `Brand Diesel`, `LPG`, and `E85`. The checked numeric values are exactly representable to one decimal place, although the CSV writes two. Preserve decimal arithmetic and display the unit explicitly. FuelWatch's public guidance also expresses retail prices in cents per litre. [WA retail-price example](https://www.wa.gov.au/government/announcements/alert-perth-motorists-check-fuelwatch-time-your-petrol-purchase)

The source has no stable station identifier. For this project, the reported-site signature must include normalized **trading name + address + locality + postcode**. Adding product and date defines an observation key. In September, address/locality/postcode/product/date alone produced 240 duplicated keys; including trading name produced none. For example, two differently named retailers report the same Brabham street address. Do not silently collapse them. A rename can create a new derived identity, so site counts mean distinct reporting signatures, not a verified census of physical forecourts.

## Why this project is timely

On 16 September 2026, the WA Government announced FuelWatch improvements involving price comparisons, location features, and consumer reporting of price and availability discrepancies. That makes reliable retail-price ingestion, provenance, and quality monitoring a relevant engineering case study. The announcement is context, not evidence that this project's observed price changes were caused by any particular event. [WA Government announcement](https://www.wa.gov.au/government/announcements/fuelwatch-upgrades-and-emergency-fuel-powers-extended-support-wa-fuel-security)

## Limits to preserve in analysis

- Prices are retailer-reported observations, not receipts or quantities sold. A simple average is not weighted by litres purchased.
- Compare the same fuel product and geographic definition. Keep `Diesel` and `Brand Diesel` distinct unless an explicit, documented transformation is requested.
- Every calendar date being represented does not prove every retailer/product reported on every day. Validate coverage separately from price changes.
- Geography and reporting identities can change. Changing composition can affect an average even when matched retailers' prices do not move.
- The name **Fuel Shock Radar** does not establish a detected shock, a causal oil-price relationship, or a wholesale-to-retail margin. This release measures reported retail-price variation only.
- Historical observations cannot establish current pump availability, discounts, or the best purchasing decision today.

## Attribution for publications and derived exports

> Source: FuelWatch Historic Fuel Prices, Government of Western Australia, cataloged by the Department of Energy, Mines, Industry Regulation and Safety; licensed under CC BY 4.0. Fuel Shock Radar validates, normalizes, and aggregates the records. Include the source month, download URL, retrieval timestamp, and checksum with derived results.

The repository's code license does not replace the dataset's license. Identify transformations, retain attribution and the license link, and do not imply endorsement by FuelWatch or the WA Government.

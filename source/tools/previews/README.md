# Setup baseline preview

Run `source/tools/setup_baseline_preview.py` with the project Python runtime.
This opens an isolated Qt sample with the main Wizard's intended order:

1. Organization.
2. Selected printers and a simulated connection/read for all three slots.
3. **Initial meter**: select any slot and switch between Meter source values and
   Parser canonical values. Both views use the same immutable sample records;
   clicking a Parser source label locates its Meter row. Only new Slot 3 requires
   confirmation. Slots 1–2 retain their existing baselines.
4. Prices, using the existing `ui.setup.steps.pricing.PricingStep` component once.
5. Final review and simulated save.

There is no separate baseline popup or duplicate pricing form. Re-reading
invalidates Slot 3 confirmation; switching devices or views preserves it.

All readings, identities, timestamps and prices are sample data. The production
parser is not invoked. The launcher overrides app, DB, log and configuration
paths with a temporary workspace before loading pricing dependencies. The
production wizard, enrollment, persistence and network routines are not invoked.
The preview does not fix or migrate the current Slot 3; no customer data changes.

# Remaining Sleeper appearances

Read-only audit of the seven remaining withheld forecasts found four unique provider athletes, all in week three:

- Tyson Bagent (11256): actuals payload has gms_active=1 and team snap counts, but no gp=1 or individual scoring statistics. His two forecasts are not inferred as played zeroes.
- Drew Lock (5854): same active-only pattern, no played appearance evidence.
- Emari Demercado (11199): absent from the weekly actuals payload.
- Blake Grupe (11058): absent from the weekly actuals payload.

Names resolved from existing player metadata; these are provider identities, not independently verified participation decisions. Source inspected directly: Sleeper NFL 2026 week-three regular-season actuals. Team snaps do not establish individual participation; active status is not a played appearance. No result zeros, DNP labels, forecast grades or model promotions were fabricated. Existing withholding is correct under available evidence.

Next evidence needed is explicit official individual participation/nonparticipation plus the league's handling of that outcome, or a later corrected provider score. A repeated fetch alone does not establish a missing player's score. No runtime code changed in this audit.

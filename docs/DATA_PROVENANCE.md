# Data provenance and interpretation

AkashChalak is a satellite-assisted air-quality decision-support prototype. Its map layers may combine observations, derived estimates, and fallback/demo records; these are not interchangeable.

## Data classes
- **Station observations:** values returned by configured monitoring sources. Preserve source identifiers and observation timestamps where available.
- **Satellite/fire detections:** remotely sensed detections with their own spatial and temporal resolution. A detection is not a ground-level pollutant measurement.
- **Interpolated grid cells:** estimates derived from nearby station observations. They should remain distinguishable from measured station points.
- **Hotspot clusters:** algorithmic groupings of input detections or observations, not independently confirmed incidents.
- **Fallback/demo data:** useful for demonstrating the interface when live sources are unavailable; never label it as live.

## Interpretation checklist
- Display the source and observation time when available.
- Keep measured, interpolated, clustered, and fallback layers visually and textually distinguishable.
- Do not imply that a satellite proxy directly measures ground-level exposure.
- Treat missing source data as unavailable rather than silently substituting a plausible-looking value.
- Preserve units and document thresholds used to create derived layers.

For consequential public-health decisions, consult authoritative monitoring and health guidance. Run the repository CI checks after changing ingestion or transformation logic.
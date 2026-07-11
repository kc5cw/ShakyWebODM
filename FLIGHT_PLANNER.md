# ShakyWebODM Flight Planner

The optional `docker-compose.shaky.yml` overlay runs:

- the ShakyWebODM image built from this repository;
- the existing local NodeODM processing node on port 3000;
- DroneRoute 0.7.1 on port 3001.

## Configuration

Add these values to `.env` before starting the overlay:

```dotenv
MAPBOX_TOKEN=pk.replace-with-your-public-mapbox-token
FLIGHTPLANNER_JWT_SECRET=replace-with-a-long-random-value
FLIGHTPLANNER_DEFAULT_VIEW=39.7392,-104.9903,11
WO_NODEODM_DIR=/var/lib/webodm-nodeodm
```

Build and start the stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.shaky.yml build webapp
docker compose -f docker-compose.yml -f docker-compose.shaky.yml up -d
```

Open **Flight Planner** from the WebODM menu. The status cards identify a stopped
planner or missing map token without requiring Docker log inspection.

## Air 3S compatibility

DroneRoute does not currently identify the DJI Air 3S as a supported autonomous
mission target. Its route geometry, estimates, and KMZ export are useful planning
tools, but every exported mission must be reviewed in the DJI application and
validated in a safe test area before flight.

This integration intentionally does not assign the Air 3S an unverified WPML drone
or payload enum. Doing so could generate a file that imports successfully but has
incorrect flight or camera behavior.

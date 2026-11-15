#!/usr/bin/env python3
"""Build the browser data set from TriMet's official GTFS feed."""

from __future__ import annotations

import csv
import io
import json
import math
from bisect import bisect_left
from collections.abc import Iterator
from datetime import date
from itertools import groupby
from pathlib import Path
from zipfile import ZipFile


FEED = Path("data/trimet-gtfs.zip")
OUTPUT = Path("data/portland-space-time.json")
SERVICE_DATE = "20261116"
WINDOW_START = 7 * 3600
WINDOW_END = 9 * 3600
SHAPE_STEP_KM = 0.05


def rows(zip_file: ZipFile, name: str) -> Iterator[dict[str, str]]:
    with zip_file.open(name) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))


def active_services(zip_file: ZipFile, service_date: str) -> set[str]:
    day = date.fromisoformat(f"{service_date[:4]}-{service_date[4:6]}-{service_date[6:]}")
    weekday = day.strftime("%A").lower()
    active = {
        row["service_id"]
        for row in rows(zip_file, "calendar.txt")
        if row[weekday] == "1" and row["start_date"] <= service_date <= row["end_date"]
    }
    for row in rows(zip_file, "calendar_dates.txt"):
        if row["date"] != service_date:
            continue
        if row["exception_type"] == "1":
            active.add(row["service_id"])
        elif row["exception_type"] == "2":
            active.discard(row["service_id"])
    return active


def seconds(value: str) -> int:
    hours, minutes, secs = (int(part) for part in value.split(":"))
    return hours * 3600 + minutes * 60 + secs


def clock(value: int) -> str:
    day, value = divmod(value, 86400)
    hours, remainder = divmod(value, 3600)
    minutes, _ = divmod(remainder, 60)
    prefix = f"+{day}d " if day else ""
    return f"{prefix}{hours:02d}:{minutes:02d}"


def main() -> None:
    mode_names = {"0": "rail/streetcar", "2": "commuter rail", "3": "bus", "6": "aerial tram"}
    output_trips: list[dict[str, object]] = []

    with ZipFile(FEED) as zip_file:
        services = active_services(zip_file, SERVICE_DATE)
        routes = {
            row["route_id"]: {
                "name": (row["route_short_name"] + " " + row["route_long_name"]).strip(),
                "mode": mode_names.get(row["route_type"], "other"),
            }
            for row in rows(zip_file, "routes.txt")
        }
        stops = {
            row["stop_id"]: (float(row["stop_lat"]), float(row["stop_lon"]), row["stop_name"])
            for row in rows(zip_file, "stops.txt")
        }
        trips = {
            row["trip_id"]: {
                "route": routes.get(row["route_id"], {"name": row["route_id"], "mode": "other"}),
                "headsign": row["trip_headsign"] or "",
                "shape_id": row["shape_id"],
            }
            for row in rows(zip_file, "trips.txt")
            if row["service_id"] in services
        }

        selected: dict[str, list[dict[str, str]]] = {}
        stop_times = rows(zip_file, "stop_times.txt")
        for trip_id, trip_rows in groupby(stop_times, key=lambda row: row["trip_id"]):
            if trip_id not in trips:
                continue
            current = sorted(trip_rows, key=lambda row: int(row["stop_sequence"]))
            if len(current) < 2:
                continue
            first_time = current[0]["departure_time"] or current[0]["arrival_time"]
            last_time = current[-1]["arrival_time"] or current[-1]["departure_time"]
            if not first_time or not last_time:
                continue
            if WINDOW_START <= seconds(first_time) < WINDOW_END:
                selected[trip_id] = current

        needed_shapes = {trips[trip_id]["shape_id"] for trip_id in selected}
        shapes: dict[str, list[tuple[float, float, float]]] = {}
        for row in rows(zip_file, "shapes.txt"):
            if row["shape_id"] in needed_shapes:
                shapes.setdefault(row["shape_id"], []).append(
                    (float(row["shape_pt_lat"]), float(row["shape_pt_lon"]), float(row["shape_dist_traveled"]))
                )
        for points in shapes.values():
            points.sort(key=lambda point: point[2])
            # shortcut: 50 m shape decimation keeps curves recognizable without a 13 MB payload
            if len(points) > 2:
                kept = [points[0]]
                for point in points[1:-1]:
                    if point[2] - kept[-1][2] >= SHAPE_STEP_KM:
                        kept.append(point)
                kept.append(points[-1])
                points[:] = kept

        used_stops = {
            stop_id
            for trip_rows in selected.values()
            for stop_id in (row["stop_id"] for row in trip_rows)
            if stop_id in stops
        }
        lats = [stops[stop_id][0] for stop_id in used_stops]
        lons = [stops[stop_id][1] for stop_id in used_stops]
        center_lat = (min(lats) + max(lats)) / 2
        center_lon = (min(lons) + max(lons)) / 2
        km_per_degree_lon = 111.32 * math.cos(math.radians(center_lat))

        def project(lat: float, lon: float) -> tuple[float, float]:
            return (lon - center_lon) * km_per_degree_lon, -(lat - center_lat) * 110.574

        point_count = 0
        for trip_id, trip_rows in selected.items():
            trip = trips[trip_id]
            shape = shapes.get(trip["shape_id"], [])
            shape_distances = [point[2] for point in shape]
            path: list[tuple[float, int, float]] = []

            for previous, current in zip(trip_rows, trip_rows[1:]):
                previous_time = seconds(previous["departure_time"] or previous["arrival_time"])
                current_time = seconds(current["arrival_time"] or current["departure_time"])
                if not path:
                    lat, lon, _ = stops[previous["stop_id"]]
                    x, z = project(lat, lon)
                    path.append((round(x, 3), previous_time, round(z, 3)))

                if shape and previous["shape_dist_traveled"] and current["shape_dist_traveled"]:
                    start_distance = float(previous["shape_dist_traveled"])
                    end_distance = float(current["shape_dist_traveled"])
                    if end_distance > start_distance:
                        first = bisect_left(shape_distances, start_distance)
                        last = bisect_left(shape_distances, end_distance)
                        for lat, lon, distance in shape[first:last]:
                            if start_distance < distance < end_distance:
                                fraction = (distance - start_distance) / (end_distance - start_distance)
                                x, z = project(lat, lon)
                                when = round(previous_time + fraction * (current_time - previous_time))
                                path.append((round(x, 3), when, round(z, 3)))

                lat, lon, _ = stops[current["stop_id"]]
                x, z = project(lat, lon)
                path.append((round(x, 3), current_time, round(z, 3)))

            # Remove duplicate points so long waits do not create invisible zero-length segments.
            clean_path: list[tuple[float, int, float]] = []
            for point in path:
                if not clean_path or point != clean_path[-1]:
                    clean_path.append(point)
            if len(clean_path) < 2:
                continue

            duration = clean_path[-1][1] - clean_path[0][1]
            distance_km = sum(
                math.hypot(right[0] - left[0], right[2] - left[2])
                for left, right in zip(clean_path, clean_path[1:])
            )
            if duration <= 0:
                continue

            flat_points: list[float] = []
            for x, when, z in clean_path:
                flat_points.extend((x, when - WINDOW_START, z))
            point_count += len(clean_path)
            route = trip["route"]
            assert isinstance(route, dict)
            output_trips.append(
                {
                    "route": route["name"],
                    "mode": route["mode"],
                    "headsign": trip["headsign"] or "—",
                    "start": stops[trip_rows[0]["stop_id"]][2],
                    "end": stops[trip_rows[-1]["stop_id"]][2],
                    "startTime": clock(clean_path[0][1]),
                    "endTime": clock(clean_path[-1][1]),
                    "distanceKm": round(distance_km, 2),
                    "speedKph": round(distance_km / (duration / 3600), 1),
                    "points": flat_points,
                }
            )

        feed_info = next(rows(zip_file, "feed_info.txt"))

    assert output_trips, "No TriMet trips were selected"
    assert all(len(trip["points"]) >= 6 for trip in output_trips)
    assert all(len(trip["points"]) % 3 == 0 for trip in output_trips)
    assert all(all(math.isfinite(value) for value in trip["points"]) for trip in output_trips)

    result = {
        "meta": {
            "city": "Portland, Oregon",
            "agency": "TriMet, Portland Streetcar, and Portland Aerial Tram",
            "serviceDate": "2026-11-16",
            "departureWindow": "07:00–09:00",
            "timezone": "America/Los_Angeles",
            "feedVersion": feed_info["feed_version"],
            "source": "https://developer.trimet.org/GTFS.shtml",
            "centerLat": round(center_lat, 6),
            "centerLon": round(center_lon, 6),
            "tripCount": len(output_trips),
            "pointCount": point_count,
        },
        "trips": output_trips,
    }
    OUTPUT.write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {OUTPUT}: {len(output_trips)} trips, {point_count:,} points")


if __name__ == "__main__":
    main()

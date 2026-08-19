import { useState } from "react";
import Map, { Marker, Popup } from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import { useStations } from "../lib/queryClient";
import { useLiveStream } from "../context/WebSocketProvider";
import { getSeverity } from "../lib/severity";
import StationCard from "../components/StationCard";
import MapMarker from "../components/MapMarker";

export default function MapView() {
  const { data: stationsMeta } = useStations();
  const { stations: liveStations } = useLiveStream();
  const [selected, setSelected] = useState<string | null>(null);

  if (!stationsMeta) return <div className="text-text-secondary">Loading stations...</div>;

  return (
    <div className="h-[70vh] rounded-md overflow-hidden border border-border-weak">
      <Map
        initialViewState={{ longitude: 78, latitude: 22, zoom: 3.5 }}
        mapStyle="https://demotiles.maplibre.org/style.json"
      >
        {stationsMeta.map((s) => {
          const severity = getSeverity(liveStations[s.station_id]);
          return (
            <Marker
              key={s.station_id}
              longitude={s.longitude}
              latitude={s.latitude}
              onClick={(e) => { e.originalEvent.stopPropagation(); setSelected(s.station_id); }}
            >
              <MapMarker severity={severity} />
            </Marker>
          );
        })}
        {selected && (() => {
          const s = stationsMeta.find((x) => x.station_id === selected)!;
          return (
            <Popup longitude={s.longitude} latitude={s.latitude} onClose={() => setSelected(null)} closeButton>
              <StationCard stationId={s.station_id} latest={liveStations[s.station_id]} />
            </Popup>
          );
        })()}
      </Map>
    </div>
  );
}

import { SimulationTimeline } from './SimulationTimeline';

interface TimelineControllerProps {
  timeline: number[];
  selectedTime?: number | null;
  loading?: boolean;
  onChange: (timeSeconds: number) => void;
}

/** Keep playback, slider selection and external URL time state behind one controller boundary. */
export function TimelineController(props: TimelineControllerProps) {
  return <SimulationTimeline {...props} />;
}

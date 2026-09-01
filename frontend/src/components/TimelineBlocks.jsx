import { useRef, useState } from 'react';
import { useTimelineDrag } from '../hooks/useTimelineDrag';

function formatTime(seconds) {
  if (seconds == null) return '00:00';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

/**
 * Блок момента на главном таймлайне (весь эпизод). Только у ВЫБРАННОГО
 * момента показываются ручки обрезки за края — у остальных клик просто
 * выбирает момент, чтобы не задеть соседний при попытке кликнуть.
 */
export function MomentBlock({ moment, videoDuration, isActive, onSelect, onCommitResize }) {
  const laneRef = useRef(null);
  const [preview, setPreview] = useState(null); // { start, end } — только во время перетаскивания

  const live = preview || { start: moment.start, end: moment.end };

  const { dragState, startDrag } = useTimelineDrag({
    laneRef,
    durationSeconds: videoDuration,
    onDrag: (deltaSeconds, mode) => {
      if (mode === 'resize-left') {
        const newStart = Math.max(0, Math.min(moment.start + deltaSeconds, moment.end - 0.2));
        setPreview({ start: newStart, end: moment.end });
      } else if (mode === 'resize-right') {
        const newEnd = Math.min(videoDuration, Math.max(moment.end + deltaSeconds, moment.start + 0.2));
        setPreview({ start: moment.start, end: newEnd });
      }
    },
    onDrop: (deltaSeconds, mode) => {
      let newStart = moment.start;
      let newEnd = moment.end;
      if (mode === 'resize-left') newStart = Math.max(0, Math.min(moment.start + deltaSeconds, moment.end - 0.2));
      if (mode === 'resize-right') newEnd = Math.min(videoDuration, Math.max(moment.end + deltaSeconds, moment.start + 0.2));
      setPreview(null);
      if (newStart !== moment.start || newEnd !== moment.end) onCommitResize(newStart, newEnd);
    },
  });

  return (
    <div
      ref={laneRef}
      className={`moment-block${isActive ? ' active' : ''}${dragState ? ' dragging' : ''}`}
      style={{ left: `${(live.start / videoDuration) * 100}%`, width: `${((live.end - live.start) / videoDuration) * 100}%` }}
      onClick={onSelect}
    >
      <div className="moment-block-label mono">{formatTime(live.start)}</div>
      {isActive && (
        <>
          <div className="resize-handle resize-handle-left" onMouseDown={startDrag('resize-left')} />
          <div className="resize-handle resize-handle-right" onMouseDown={startDrag('resize-right')} />
        </>
      )}
    </div>
  );
}

/**
 * Клип на дорожке (tracks-panel) — можно двигать целиком (тело блока) или
 * обрезать за левый/правый край. Обрезка меняет и position_*, и trim_*
 * синхронно (сдвигаем, какая часть исходника используется), перемещение —
 * только position_* (что играет, не меняется, меняется когда).
 */
export function ClipBlock({ clip, momentDuration, isSelected, onSelect, onCommitChange }) {
  const laneRef = useRef(null);
  const [preview, setPreview] = useState(null);

  const live = preview || {
    position_start: clip.position_start,
    position_end: clip.position_end,
    trim_start: clip.trim_start,
    trim_end: clip.trim_end,
  };

  function computePreview(deltaSeconds, mode) {
    const clipDuration = clip.position_end - clip.position_start;

    if (mode === 'move') {
      let newStart = clip.position_start + deltaSeconds;
      newStart = Math.max(0, Math.min(newStart, momentDuration - clipDuration));
      const actualDelta = newStart - clip.position_start;
      return {
        position_start: newStart,
        position_end: clip.position_end + actualDelta,
        trim_start: clip.trim_start,
        trim_end: clip.trim_end,
      };
    }

    if (mode === 'resize-left') {
      // delta не может увести position_start ниже 0, trim_start ниже 0,
      // и не может сократить клип короче 0.2с
      const minDelta = -Math.min(clip.position_start, clip.trim_start);
      const maxDelta = clipDuration - 0.2;
      const boundedDelta = Math.max(minDelta, Math.min(deltaSeconds, maxDelta));
      return {
        position_start: clip.position_start + boundedDelta,
        position_end: clip.position_end,
        trim_start: clip.trim_start + boundedDelta,
        trim_end: clip.trim_end,
      };
    }

    if (mode === 'resize-right') {
      // delta не может увести position_end за пределы момента, trim_end —
      // за пределы длины исходника, и не может сократить клип короче 0.2с
      const sourceDuration = clip.source_duration ?? clip.trim_end;
      const maxDelta = Math.min(momentDuration - clip.position_end, sourceDuration - clip.trim_end);
      const minDelta = -(clipDuration - 0.2);
      const boundedDelta = Math.max(minDelta, Math.min(deltaSeconds, maxDelta));
      return {
        position_start: clip.position_start,
        position_end: clip.position_end + boundedDelta,
        trim_start: clip.trim_start,
        trim_end: clip.trim_end + boundedDelta,
      };
    }

    return live;
  }

  const { dragState, startDrag } = useTimelineDrag({
    laneRef,
    durationSeconds: momentDuration,
    onDrag: (deltaSeconds, mode) => setPreview(computePreview(deltaSeconds, mode)),
    onDrop: (deltaSeconds, mode) => {
      const result = computePreview(deltaSeconds, mode);
      setPreview(null);
      onCommitChange(result);
    },
  });

  return (
    <div
      ref={laneRef}
      className={`track-clip-block track-clip-${clip._trackType}${isSelected ? ' active' : ''}${dragState ? ' dragging' : ''}`}
      style={{
        left: `${(live.position_start / momentDuration) * 100}%`,
        width: `${((live.position_end - live.position_start) / momentDuration) * 100}%`,
        backgroundImage: clip._trackType === 'video' ? `url(${clip._thumbnailUrl})` : undefined,
      }}
      onMouseDown={startDrag('move')}
      onClick={(e) => { e.stopPropagation(); onSelect(); }}
    >
      <div className="resize-handle resize-handle-left" onMouseDown={startDrag('resize-left')} />
      <span className="track-clip-label">{formatTime(live.position_start)}–{formatTime(live.position_end)}</span>
      <div className="resize-handle resize-handle-right" onMouseDown={startDrag('resize-right')} />
    </div>
  );
}

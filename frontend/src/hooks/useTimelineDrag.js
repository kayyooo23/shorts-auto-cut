import { useCallback, useRef, useState } from 'react';

/**
 * Универсальный хук для перетаскивания/обрезки блоков на таймлайне —
 * используется и для границ момента (main timeline), и для клипов на
 * дорожках (tracks-panel). Не привязан к конкретной вёрстке: принимает
 * DOM-элемент дорожки (для расчёта ширины в пикселях) и колбэк, в который
 * отдаёт итоговый сдвиг в СЕКУНДАХ при отпускании кнопки мыши.
 *
 * mode: 'move' | 'resize-left' | 'resize-right' — что именно тащим.
 * onDrag(deltaSeconds, mode) — вызывается на каждое движение мыши (для
 *   визуального фидбека в реальном времени, без обращения к API).
 * onDrop(deltaSeconds, mode) — вызывается один раз при отпускании кнопки —
 *   здесь обычно и идёт обновление через API.
 */
export function useTimelineDrag({ laneRef, durationSeconds, onDrag, onDrop }) {
  const [dragState, setDragState] = useState(null); // { mode } | null
  const startXRef = useRef(0);

  const startDrag = useCallback((mode) => (e) => {
    e.preventDefault();
    e.stopPropagation();
    startXRef.current = e.clientX;
    setDragState({ mode });

    const laneWidth = laneRef.current?.getBoundingClientRect().width || 1;
    const secondsPerPixel = durationSeconds / laneWidth;

    function handleMouseMove(moveEvent) {
      const deltaPixels = moveEvent.clientX - startXRef.current;
      const deltaSeconds = deltaPixels * secondsPerPixel;
      onDrag?.(deltaSeconds, mode);
    }

    function handleMouseUp(upEvent) {
      const deltaPixels = upEvent.clientX - startXRef.current;
      const deltaSeconds = deltaPixels * secondsPerPixel;
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      setDragState(null);
      onDrop?.(deltaSeconds, mode);
    }

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  }, [laneRef, durationSeconds, onDrag, onDrop]);

  return { dragState, startDrag };
}

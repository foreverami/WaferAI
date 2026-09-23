/**
 * 0/1/2 웨이퍼 맵을 캔버스에 그린다.
 *
 * 색은 학습에 쓰인 LUT 와 같아야 한다. 엔지니어가 보는 그림과 모델이 본 그림이
 * 다르면 히트맵을 겹쳤을 때 설명이 어긋난다.
 *   0 배경 검정 / 1 정상 다이 초록 / 2 결함 다이 노랑
 */
import { useEffect, useRef } from 'react'

const LUT = [
  [0, 0, 0],
  [0, 255, 0],
  [255, 255, 0],
]

export default function WaferMap({ map, className = '' }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !Array.isArray(map) || map.length === 0) return

    const height = map.length
    const width = map[0].length
    canvas.width = width
    canvas.height = height

    const context = canvas.getContext('2d')
    const image = context.createImageData(width, height)
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const [r, g, b] = LUT[map[y][x]] || LUT[0]
        const offset = (y * width + x) * 4
        image.data[offset] = r
        image.data[offset + 1] = g
        image.data[offset + 2] = b
        image.data[offset + 3] = 255
      }
    }
    context.putImageData(image, 0, 0)
  }, [map])

  if (!Array.isArray(map) || map.length === 0) {
    return (
      <div
        className={`flex items-center justify-center rounded-lg bg-black text-xs text-muted ${className}`}
      >
        맵 없음
      </div>
    )
  }

  return (
    <canvas
      ref={canvasRef}
      className={`wafer-image w-full rounded-lg bg-black ${className}`}
      style={{ aspectRatio: '1 / 1', objectFit: 'contain' }}
    />
  )
}

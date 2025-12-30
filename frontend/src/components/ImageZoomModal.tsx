import React, { useState, useEffect, useRef } from 'react';
import { X, ZoomIn, ZoomOut, Maximize2, Minimize2, RotateCw, Download, ChevronLeft, ChevronRight } from 'lucide-react';

interface ImageZoomModalProps {
  isOpen: boolean;
  onClose: () => void;
  images: string[];
  initialIndex?: number;
}

const ImageZoomModal: React.FC<ImageZoomModalProps> = ({ isOpen, onClose, images, initialIndex = 0 }) => {
  const [currentIndex, setCurrentIndex] = useState(initialIndex);
  const [scale, setScale] = useState(1);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [rotation, setRotation] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  
  const containerRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);

  useEffect(() => {
    if (isOpen) {
      setCurrentIndex(initialIndex);
      resetZoom();
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = 'unset';
    }
    return () => {
      document.body.style.overflow = 'unset';
    };
  }, [isOpen, initialIndex]);

  const resetZoom = () => {
    setScale(1.5); // 기본적으로 1.5배 확대한 상태로 시작 (사용자 요청: 2-4배 크게 보기 위해)
    setPosition({ x: 0, y: 0 });
    setRotation(0);
  };

  const handleZoomIn = () => setScale(prev => Math.min(prev + 0.5, 5));
  const handleZoomOut = () => setScale(prev => Math.max(prev - 0.5, 0.5));
  const handleRotate = () => setRotation(prev => (prev + 90) % 360);

  const handleMouseDown = (e: React.MouseEvent) => {
    if (scale <= 1) return;
    setIsDragging(true);
    setDragStart({ x: e.clientX - position.x, y: e.clientY - position.y });
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging) return;
    setPosition({
      x: e.clientX - dragStart.x,
      y: e.clientY - dragStart.y
    });
  };

  const handleMouseUp = () => setIsDragging(false);

  const handlePrev = () => {
    setCurrentIndex(prev => (prev > 0 ? prev - 1 : images.length - 1));
    resetZoom();
  };

  const handleNext = () => {
    setCurrentIndex(prev => (prev < images.length - 1 ? prev + 1 : 0));
    resetZoom();
  };

  const handleDownload = () => {
    const link = document.createElement('a');
    link.href = images[currentIndex];
    link.download = `image_${currentIndex + 1}.png`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex flex-col bg-black bg-opacity-90 backdrop-blur-sm transition-all duration-300">
      {/* Header Controls */}
      <div className="flex items-center justify-between p-4 text-white bg-black bg-opacity-50 z-10">
        <div className="flex items-center space-x-4">
          <span className="text-sm font-medium">
            {currentIndex + 1} / {images.length}
          </span>
          <button onClick={handleDownload} className="p-2 hover:bg-white hover:bg-opacity-10 rounded-full transition-colors" title="다운로드">
            <Download size={20} />
          </button>
        </div>
        
        <div className="flex items-center space-x-2">
          <button onClick={handleZoomOut} className="p-2 hover:bg-white hover:bg-opacity-10 rounded-full transition-colors" title="축소">
            <ZoomOut size={20} />
          </button>
          <span className="text-sm min-w-[3rem] text-center">{Math.round(scale * 100)}%</span>
          <button onClick={handleZoomIn} className="p-2 hover:bg-white hover:bg-opacity-10 rounded-full transition-colors" title="확대">
            <ZoomIn size={20} />
          </button>
          <div className="w-px h-4 bg-white bg-opacity-20 mx-2" />
          <button onClick={handleRotate} className="p-2 hover:bg-white hover:bg-opacity-10 rounded-full transition-colors" title="회전">
            <RotateCw size={20} />
          </button>
          <button onClick={resetZoom} className="p-2 hover:bg-white hover:bg-opacity-10 rounded-full transition-colors" title="초기화">
            <Maximize2 size={20} />
          </button>
          <button onClick={onClose} className="p-2 hover:bg-red-500 rounded-full transition-colors ml-4" title="닫기">
            <X size={24} />
          </button>
        </div>
      </div>

      {/* Main Image View */}
      <div 
        ref={containerRef}
        className="flex-grow relative overflow-hidden flex items-center justify-center cursor-grab active:cursor-grabbing"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        {images.length > 1 && (
          <>
            <button 
              onClick={handlePrev}
              className="absolute left-4 z-10 p-3 bg-black bg-opacity-30 hover:bg-opacity-50 text-white rounded-full transition-all"
            >
              <ChevronLeft size={32} />
            </button>
            <button 
              onClick={handleNext}
              className="absolute right-4 z-10 p-3 bg-black bg-opacity-30 hover:bg-opacity-50 text-white rounded-full transition-all"
            >
              <ChevronRight size={32} />
            </button>
          </>
        )}

        <div
          style={{
            transform: `translate(${position.x}px, ${position.y}px) scale(${scale}) rotate(${rotation}deg)`,
            transition: isDragging ? 'none' : 'transform 0.2s ease-out',
          }}
        >
          <img
            ref={imageRef}
            src={images[currentIndex]}
            alt={`Preview ${currentIndex}`}
            className="max-w-full max-h-[85vh] select-none shadow-2xl rounded-sm"
            draggable={false}
          />
        </div>
      </div>

      {/* Thumbnails Strip */}
      {images.length > 1 && (
        <div className="p-4 bg-black bg-opacity-50 overflow-x-auto no-scrollbar">
          <div className="flex justify-center space-x-2">
            {images.map((img, idx) => (
              <button
                key={idx}
                onClick={() => {
                  setCurrentIndex(idx);
                  resetZoom();
                }}
                className={`flex-shrink-0 w-16 h-16 rounded-md overflow-hidden border-2 transition-all ${
                  currentIndex === idx ? 'border-blue-500 scale-110' : 'border-transparent opacity-50 hover:opacity-100'
                }`}
              >
                <img src={img} alt={`Thumb ${idx}`} className="w-full h-full object-cover" />
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default ImageZoomModal;

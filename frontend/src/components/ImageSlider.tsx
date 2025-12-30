import React, { useState } from 'react';
import { ChevronLeft, ChevronRight, Maximize2 } from 'lucide-react';

interface ImageSliderProps {
  images: string[];
  onImageClick: (index: number) => void;
}

const ImageSlider: React.FC<ImageSliderProps> = ({ images, onImageClick }) => {
  const [currentIndex, setCurrentIndex] = useState(0);

  if (!images || images.length === 0) return null;

  const handlePrev = (e: React.MouseEvent) => {
    e.stopPropagation();
    setCurrentIndex((prev) => (prev > 0 ? prev - 1 : images.length - 1));
  };

  const handleNext = (e: React.MouseEvent) => {
    e.stopPropagation();
    setCurrentIndex((prev) => (prev < images.length - 1 ? prev + 1 : 0));
  };

  return (
    <div className="relative group w-full max-w-sm mx-auto mt-2 rounded-xl overflow-hidden bg-gray-50 border border-gray-200 shadow-sm transition-all hover:shadow-md">
      {/* 이미지 출력 */}
      <div 
        className="relative aspect-video flex items-center justify-center cursor-pointer overflow-hidden"
        onClick={() => onImageClick(currentIndex)}
      >
        <img
          src={images[currentIndex]}
          alt={`슬라이드 이미지 ${currentIndex + 1}`}
          className="max-w-full max-h-full object-contain transition-transform duration-300 group-hover:scale-105"
        />
        
        {/* 오버레이 버튼 (확대) */}
        <div className="absolute inset-0 bg-black bg-opacity-0 group-hover:bg-opacity-10 transition-all flex items-center justify-center">
          <div className="opacity-0 group-hover:opacity-100 transform translate-y-2 group-hover:translate-y-0 transition-all bg-white p-2 rounded-full shadow-lg">
            <Maximize2 size={20} className="text-gray-700" />
          </div>
        </div>
      </div>

      {/* 네비게이션 버튼 (이미지가 2개 이상일 때만) */}
      {images.length > 1 && (
        <>
          <button
            onClick={handlePrev}
            className="absolute left-2 top-1/2 -translate-y-1/2 p-1.5 bg-white/80 hover:bg-white text-gray-800 rounded-full shadow-md opacity-0 group-hover:opacity-100 transition-all z-10 hover:scale-110"
          >
            <ChevronLeft size={20} />
          </button>
          <button
            onClick={handleNext}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 bg-white/80 hover:bg-white text-gray-800 rounded-full shadow-md opacity-0 group-hover:opacity-100 transition-all z-10 hover:scale-110"
          >
            <ChevronRight size={20} />
          </button>

          {/* 인디케이터 */}
          <div className="absolute bottom-2 left-1/2 -translate-x-1/2 flex space-x-1.5 px-2 py-1 bg-black/20 backdrop-blur-sm rounded-full">
            {images.map((_, idx) => (
              <div
                key={idx}
                className={`w-1.5 h-1.5 rounded-full transition-all ${
                  currentIndex === idx ? 'bg-white scale-125' : 'bg-white/50 hover:bg-white/80'
                }`}
              />
            ))}
          </div>

          {/* 카운터 배지 */}
          <div className="absolute top-2 right-2 px-2 py-1 bg-black/40 backdrop-blur-sm text-white text-[10px] font-medium rounded-md">
            {currentIndex + 1} / {images.length}
          </div>
        </>
      )}
    </div>
  );
};

export default ImageSlider;

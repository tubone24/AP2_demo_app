"use client";

import { useCallback, useEffect, useState } from "react";
import useEmblaCarousel from "embla-carousel-react";
import { CartCard } from "./CartCard";
import { Button } from "@/components/ui/button";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface CartCarouselProps {
  cartCandidates: any[];
  onSelectCart?: (cartCandidate: any) => void;
  onViewDetails?: (cartCandidate: any) => void;
  className?: string;
}

export function CartCarousel({
  cartCandidates,
  onSelectCart,
  onViewDetails,
  className,
}: CartCarouselProps) {
  const [emblaRef, emblaApi] = useEmblaCarousel({
    align: "start",
    loop: false,
    slidesToScroll: 1,
  });

  const [prevBtnEnabled, setPrevBtnEnabled] = useState(false);
  const [nextBtnEnabled, setNextBtnEnabled] = useState(false);

  const scrollPrev = useCallback(() => {
    if (emblaApi) emblaApi.scrollPrev();
  }, [emblaApi]);

  const scrollNext = useCallback(() => {
    if (emblaApi) emblaApi.scrollNext();
  }, [emblaApi]);

  const onSelect = useCallback(() => {
    if (!emblaApi) return;
    setPrevBtnEnabled(emblaApi.canScrollPrev());
    setNextBtnEnabled(emblaApi.canScrollNext());
  }, [emblaApi]);

  useEffect(() => {
    if (!emblaApi) return;
    onSelect();
    emblaApi.on("select", onSelect);
    emblaApi.on("reInit", onSelect);
  }, [emblaApi, onSelect]);

  if (cartCandidates.length === 0) {
    return null;
  }

  return (
    <div className={cn("relative", className)}>
      <div className="overflow-hidden" ref={emblaRef}>
        <div className="flex gap-4">
          {cartCandidates.map((cartCandidate) => (
            <div
              key={cartCandidate.artifact_id || cartCandidate.cart_mandate?.id}
              className="flex-[0_0_320px] min-w-0"
            >
              <CartCard
                cartCandidate={cartCandidate}
                onSelectCart={onSelectCart}
                onViewDetails={onViewDetails}
              />
            </div>
          ))}
        </div>
      </div>

      {/* ナビゲーションボタン */}
      {cartCandidates.length > 1 && (
        <>
          <Button
            variant="outline"
            size="icon"
            className={cn(
              "absolute left-2 top-1/2 -translate-y-1/2 z-10 rounded-full shadow-md",
              !prevBtnEnabled && "opacity-50 cursor-not-allowed"
            )}
            onClick={scrollPrev}
            disabled={!prevBtnEnabled}
          >
            <ChevronLeft className="w-4 h-4" />
          </Button>

          <Button
            variant="outline"
            size="icon"
            className={cn(
              "absolute right-2 top-1/2 -translate-y-1/2 z-10 rounded-full shadow-md",
              !nextBtnEnabled && "opacity-50 cursor-not-allowed"
            )}
            onClick={scrollNext}
            disabled={!nextBtnEnabled}
          >
            <ChevronRight className="w-4 h-4" />
          </Button>
        </>
      )}
    </div>
  );
}

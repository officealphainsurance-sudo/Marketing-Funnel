import React from 'react';
import { Composition } from 'remotion';
import { AuthorityReel } from './Composition.jsx';

export const RemotionRoot = () => {
  return (
    <>
      <Composition
        id="AuthorityReel"
        component={AuthorityReel}
        durationInFrames={750}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          hookText:     "Selling your home shouldn't cost you sleep.",
          problemText:  "Most agents make you juggle showings, staging stress, and endless uncertainty. It doesn't have to be that way.",
          solutionText: "If you value expert guidance, white-glove service, and a proven strategy that gets results — that's exactly what I deliver. Everything I touch turns to sold.",
          ctaText:      "Let's get your home sold with zero stress. Call W Real Estate, LLC at 601-499-0952 today.",
          brandKey:     "w-real-estate",
        }}
      />
    </>
  );
};
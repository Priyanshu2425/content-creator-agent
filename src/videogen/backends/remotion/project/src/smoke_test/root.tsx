import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {CaptionDemo} from './CaptionDemo';

// 8 words × (9+3) stride + annotation hold = ~145 frames; use 5s @ 30fps = 150
const RemotionRoot: React.FC = () => (
  <Composition
    id="CaptionDemo"
    component={CaptionDemo}
    width={1080}
    height={1920}
    fps={30}
    durationInFrames={150}
    defaultProps={{}}
  />
);

registerRoot(RemotionRoot);

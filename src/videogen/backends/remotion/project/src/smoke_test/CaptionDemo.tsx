import React from 'react';
import {AbsoluteFill} from 'remotion';
import {HighlightCaptions} from './HighlightCaptions';

export const CaptionDemo: React.FC = () => {
	return (
		<AbsoluteFill style={{backgroundColor: '#1a1a1a'}}>
			<AbsoluteFill
				style={{
					background:
						'radial-gradient(circle at 50% 30%, #3a3a3a 0%, #1a1a1a 70%)',
				}}
			/>

			<HighlightCaptions
				startFrame={0}
				wordDurationInFrames={9}
				boxGapInFrames={3}
				topPosition="22%"
				maxWidth={820}
				fontSize={58}
				lines={[
					{words: ['Bottom']},
					{words: ['line']},
					{words: ['is']},
					{words: ['no']},
					{words: ["one's"]},
					{words: ['got']},
					{words: ['your']},
					{words: ['flavor']},
				]}
				annotation={{
					text: "We help you add\nsome spice (or\nlaughing gas\nif you will)",
					startFrame: 95,
					top: '64%',
					left: '58%',
					width: 230,
					rotation: -3,
					arrow: 'up-left',
				}}
			/>

			<div
				style={{
					position: 'absolute',
					bottom: 40,
					left: '50%',
					transform: 'translateX(-50%)',
					color: '#E8FF3D',
					fontFamily: 'Arial, sans-serif',
					fontSize: 16,
					letterSpacing: '0.08em',
					fontWeight: 700,
				}}
			>
				BLUMM CREATIVE
			</div>
		</AbsoluteFill>
	);
};

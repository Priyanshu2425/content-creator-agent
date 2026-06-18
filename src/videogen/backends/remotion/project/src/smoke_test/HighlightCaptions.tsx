import React from 'react';
import {
	AbsoluteFill,
	interpolate,
	Sequence,
	spring,
	useCurrentFrame,
	useVideoConfig,
} from 'remotion';

/**
 * HighlightCaptions
 * -----------------
 * A reusable Remotion component that recreates the "neon highlighter box"
 * caption style: bold black text on a bright box (yellow by default),
 * phrases broken into separate boxes that wrap naturally like highlighter
 * marks over text, with a word-by-word reveal inside each box.
 *
 * Usage:
 *
 * <HighlightCaptions
 *   lines={[
 *     { words: ['Bottom'], },
 *     { words: ['line'] },
 *     { words: ['is'] },
 *     { words: ['no'] },
 *     { words: ["one's"] },
 *     { words: ['got'] },
 *     { words: ['your'] },
 *     { words: ['flavor'] },
 *   ]}
 *   startFrame={0}
 *   wordDurationInFrames={10}
 * />
 *
 * Each item in `lines` is rendered as one highlighter box. Group words
 * together in one box if you want multiple words to appear together
 * inside the same box (they'll still reveal word-by-word).
 */

export type CaptionBox = {
	/** Words inside this box, revealed one at a time */
	words: string[];
	/** Optional manual rotation override in degrees */
	rotation?: number;
};

export type Annotation = {
	text: string;
	/** Frame (relative to component's local timeline) the annotation appears */
	startFrame: number;
	/** Position as % of frame width/height */
	top: string;
	left: string;
	/** Rotation in degrees, for handwritten tilt */
	rotation?: number;
	/** Width of the text block */
	width?: number;
	/** Arrow pointing direction: 'up-left' | 'up-right' | 'down-left' | 'down-right' | 'none' */
	arrow?: 'up-left' | 'up-right' | 'down-left' | 'down-right' | 'none';
};

export type HighlightCaptionsProps = {
	/** The caption boxes, in reveal order */
	lines: CaptionBox[];
	/** Frame (relative to this component) at which the first box starts appearing */
	startFrame?: number;
	/** How many frames each word takes to pop in before the next word starts */
	wordDurationInFrames?: number;
	/** Extra gap (in frames) before a NEW box starts, on top of word reveal timing */
	boxGapInFrames?: number;
	/** Highlight box background color */
	highlightColor?: string;
	/** Text color inside boxes */
	textColor?: string;
	/** Font size in px */
	fontSize?: number;
	/** Font family */
	fontFamily?: string;
	/** Max width (px) of the caption block, used for wrapping logic */
	maxWidth?: number;
	/** Vertical position from top, as a CSS value e.g. '28%' */
	topPosition?: string;
	/** Optional handwritten-style annotation with arrow */
	annotation?: Annotation;
	/** Color of the annotation text + arrow */
	annotationColor?: string;
};

const DEFAULT_ROTATIONS = [-1.5, 1, -0.5, 2, -2, 0.5, -1, 1.5];

/**
 * A single highlighter box containing one or more words that reveal
 * word-by-word via spring scale/opacity pops.
 */
const HighlightBox: React.FC<{
	box: CaptionBox;
	index: number;
	wordDurationInFrames: number;
	highlightColor: string;
	textColor: string;
	fontSize: number;
	fontFamily: string;
}> = ({box, index, wordDurationInFrames, highlightColor, textColor, fontSize, fontFamily}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();

	const rotation =
		box.rotation ?? DEFAULT_ROTATIONS[index % DEFAULT_ROTATIONS.length];

	// Overall box entrance (pops the whole box in as soon as its first word starts)
	const boxEntrance = spring({
		frame,
		fps,
		config: {damping: 12, stiffness: 180, mass: 0.6},
	});

	const boxOpacity = interpolate(boxEntrance, [0, 1], [0, 1]);
	const boxScale = interpolate(boxEntrance, [0, 1], [0.7, 1]);

	return (
		<div
			style={{
				display: 'inline-flex',
				margin: '6px 8px',
				transform: `rotate(${rotation}deg) scale(${boxScale})`,
				opacity: boxOpacity,
			}}
		>
			<div
				style={{
					backgroundColor: highlightColor,
					padding: '6px 22px 14px 22px',
					borderRadius: 4,
					display: 'inline-flex',
					gap: '0.4em',
					boxShadow: '0 2px 0 rgba(0,0,0,0.15)',
				}}
			>
				{box.words.map((word, wordIndex) => {
					const wordStart = wordIndex * wordDurationInFrames;
					const wordFrame = frame - wordStart;

					const wordSpring = spring({
						frame: wordFrame,
						fps,
						config: {damping: 11, stiffness: 200, mass: 0.5},
					});

					const opacity = wordFrame < 0 ? 0 : interpolate(wordSpring, [0, 1], [0, 1]);
					const scale = wordFrame < 0 ? 0.5 : interpolate(wordSpring, [0, 1], [0.5, 1]);
					const translateY = wordFrame < 0 ? 14 : interpolate(wordSpring, [0, 1], [14, 0]);

					return (
						<span
							key={wordIndex}
							style={{
								display: 'inline-block',
								fontFamily,
								fontWeight: 800,
								fontSize,
								color: textColor,
								lineHeight: 1.05,
								letterSpacing: '-0.01em',
								opacity,
								transform: `translateY(${translateY}px) scale(${scale})`,
								whiteSpace: 'nowrap',
							}}
						>
							{word}
						</span>
					);
				})}
			</div>
		</div>
	);
};

const ARROW_PATHS: Record<string, string> = {
	'up-left': 'M70 60 C 50 30, 25 15, 5 8 M5 8 L 14 16 M5 8 L 16 4',
	'up-right': 'M5 60 C 25 30, 50 15, 65 8 M65 8 L 56 16 M65 8 L 54 4',
	'down-left': 'M70 8 C 50 35, 25 50, 5 58 M5 58 L 16 52 M5 58 L 8 65',
	'down-right': 'M5 8 C 25 35, 50 50, 65 58 M65 58 L 54 52 M65 58 L 62 65',
};

const AnnotationLayer: React.FC<{
	annotation: Annotation;
	color: string;
}> = ({annotation, color}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();

	const localFrame = frame - annotation.startFrame;
	if (localFrame < 0) return null;

	const entrance = spring({
		frame: localFrame,
		fps,
		config: {damping: 14, stiffness: 140, mass: 0.7},
	});

	const opacity = interpolate(entrance, [0, 1], [0, 1]);
	const scale = interpolate(entrance, [0, 1], [0.85, 1]);

	return (
		<div
			style={{
				position: 'absolute',
				top: annotation.top,
				left: annotation.left,
				width: annotation.width ?? 220,
				opacity,
				transform: `rotate(${annotation.rotation ?? -4}deg) scale(${scale})`,
			}}
		>
			<div
				style={{
					fontFamily: "'Caveat', 'Comic Sans MS', cursive",
					fontSize: 30,
					fontWeight: 600,
					color,
					lineHeight: 1.15,
					textAlign: 'left',
				}}
			>
				{annotation.text}
			</div>
			{annotation.arrow && annotation.arrow !== 'none' && (
				<svg
					width={75}
					height={70}
					viewBox="0 0 75 70"
					style={{
						position: 'absolute',
						top: annotation.arrow.startsWith('up') ? -65 : 50,
						left: annotation.arrow.endsWith('left') ? -40 : '90%',
						overflow: 'visible',
					}}
				>
					<path
						d={ARROW_PATHS[annotation.arrow]}
						stroke={color}
						strokeWidth={3}
						fill="none"
						strokeLinecap="round"
						strokeLinejoin="round"
					/>
				</svg>
			)}
		</div>
	);
};

export const HighlightCaptions: React.FC<HighlightCaptionsProps> = ({
	lines,
	startFrame = 0,
	wordDurationInFrames = 10,
	boxGapInFrames = 4,
	highlightColor = '#E8FF3D',
	textColor = '#0a0a0a',
	fontSize = 56,
	fontFamily = "'Helvetica Neue', Arial, sans-serif",
	maxWidth = 760,
	topPosition = '24%',
	annotation,
	annotationColor = '#E8FF3D',
}) => {
	// Compute the start frame (within the Sequence) of each box based on
	// how many words came before it, so reveal flows continuously.
	let cumulativeFrame = 0;
	const boxStarts = lines.map((box) => {
		const thisStart = cumulativeFrame;
		cumulativeFrame += box.words.length * wordDurationInFrames + boxGapInFrames;
		return thisStart;
	});

	return (
		<Sequence from={startFrame} layout="none">
			<AbsoluteFill>
				<div
					style={{
						position: 'absolute',
						top: topPosition,
						left: '50%',
						transform: 'translateX(-50%)',
						width: maxWidth,
						display: 'flex',
						flexWrap: 'wrap',
						justifyContent: 'center',
						alignItems: 'center',
					}}
				>
					{lines.map((box, i) => (
						<Sequence key={i} from={boxStarts[i]} layout="none">
							<HighlightBox
								box={box}
								index={i}
								wordDurationInFrames={wordDurationInFrames}
								highlightColor={highlightColor}
								textColor={textColor}
								fontSize={fontSize}
								fontFamily={fontFamily}
							/>
						</Sequence>
					))}
				</div>
				{annotation && (
					<AnnotationLayer annotation={annotation} color={annotationColor} />
				)}
			</AbsoluteFill>
		</Sequence>
	);
};

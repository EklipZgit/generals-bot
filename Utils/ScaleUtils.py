import typing


def rescale_color(
        valToScale: float,
        valueMin: float,
        valueMax: float,
        colorMin: typing.Tuple[int, int, int],
        colorMax: typing.Tuple[int, int, int]
) -> typing.Tuple[int, int, int]:
    rMin, gMin, bMin = colorMin
    rMax, gMax, bMax = colorMax

    r = min(255, int(rescale_value(valToScale, valueMin, valueMax, rMin, rMax)))
    g = min(255, int(rescale_value(valToScale, valueMin, valueMax, gMin, gMax)))
    b = min(255, int(rescale_value(valToScale, valueMin, valueMax, bMin, bMax)))

    return r, g, b


def rescale_value(
        valToScale: float,
        valueMin: float,
        valueMax: float,
        newScaleMin: float,
        newScaleMax: float,
) -> float:
    # Figure out how 'wide' each range is
    leftSpan = valueMax - valueMin
    rightSpan = newScaleMax - newScaleMin

    if leftSpan == 0:
        leftSpan = 1

    # Convert the left range into a 0-1 range (float)
    valueScaled = float(valToScale - valueMin) / float(leftSpan)

    # Convert the 0-1 range into a value in the right range.
    return newScaleMin + (valueScaled * rightSpan)

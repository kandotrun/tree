public enum WateringCountdownProgress {
    public static func remainingFraction(
        remainingMilliseconds: Int,
        scheduledMilliseconds: Int
    ) -> Double? {
        guard scheduledMilliseconds > 0 else { return nil }

        let fraction = Double(remainingMilliseconds) / Double(scheduledMilliseconds)
        return min(max(fraction, 0), 1)
    }
}

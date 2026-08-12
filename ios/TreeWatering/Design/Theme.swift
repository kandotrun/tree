import SwiftUI
import TreeCore

extension Color {
    /// Interactive tint follows the system's light and dark appearances.
    static let treeAccent = Color("AccentColor")
    /// A darker fill keeps white text legible on the physical-action button.
    static let treeActionFill = Color(red: 0.075, green: 0.278, blue: 0.196)
    static let treeWarning = Color.red
}

extension WateringAvailability {
    var japaneseTitle: String {
        switch self {
        case .bootGuard: "準備中"
        case .ready: "待機中"
        case .unarmed: "給水は無効です"
        case .watering: "給水中"
        case .error: "デバイスエラー"
        case .unknown: "状態を確認中"
        }
    }

    var japaneseDetail: String {
        switch self {
        case .bootGuard: "安全待機が終わるまでお待ちください"
        case .ready: "給水を開始できます"
        case .unarmed: "実機テスト後に端末を有効化してください"
        case .watering: "デバイスのタイマーで自動停止します"
        case .error: "デバイスと配線を確認してください"
        case .unknown: "状態を確認しています"
        }
    }

    var symbolName: String {
        switch self {
        case .bootGuard: "hourglass"
        case .ready: "checkmark.circle.fill"
        case .unarmed: "lock.fill"
        case .watering: "drop.fill"
        case .error: "exclamationmark.triangle.fill"
        case .unknown: "questionmark.circle.fill"
        }
    }

    var tint: Color {
        switch self {
        case .ready: .green
        case .watering: .blue
        case .unarmed, .bootGuard, .unknown: .orange
        case .error: .red
        }
    }
}

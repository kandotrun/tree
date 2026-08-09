import SwiftUI
import TreeCore

extension Color {
    static let treeCanvas = Color(red: 0.953, green: 0.949, blue: 0.914)
    static let treeInk = Color(red: 0.075, green: 0.145, blue: 0.110)
    static let treeForest = Color(red: 0.075, green: 0.278, blue: 0.196)
    static let treeLeaf = Color(red: 0.286, green: 0.514, blue: 0.333)
    static let treeWater = Color(red: 0.122, green: 0.557, blue: 0.663)
    static let treeCard = Color.white.opacity(0.76)
    static let treeWarning = Color(red: 0.745, green: 0.235, blue: 0.176)
}

extension AtomState {
    var japaneseTitle: String {
        switch self {
        case .bootGuard: "起動を確認中"
        case .idle: "水やりできます"
        case .watering: "給水中"
        case .error: "端末エラー"
        case .unknown: "状態を確認中"
        }
    }

    var japaneseDetail: String {
        switch self {
        case .bootGuard: "安全待機が終わるまで少し待ってください"
        case .idle: "ポンプは停止しています"
        case .watering: "指示した時間で自動停止します"
        case .error: "端末と配線を確認してください"
        case .unknown: "アプリが未対応の端末状態です"
        }
    }

    var tint: Color {
        switch self {
        case .idle: .treeLeaf
        case .watering: .treeWater
        case .bootGuard, .unknown: .orange
        case .error: .treeWarning
        }
    }
}

struct TreeCardModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(20)
            .background(Color.treeCard)
            .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 28, style: .continuous)
                    .stroke(Color.white.opacity(0.8), lineWidth: 1)
            }
            .shadow(color: Color.treeInk.opacity(0.07), radius: 24, y: 12)
    }
}

extension View {
    func treeCard() -> some View {
        modifier(TreeCardModifier())
    }
}

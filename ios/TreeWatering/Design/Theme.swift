import SwiftUI
import TreeCore

extension Color {
    static let treeCanvas = Color(red: 0.953, green: 0.949, blue: 0.914)
    static let treeInk = Color(red: 0.075, green: 0.145, blue: 0.110)
    static let treeForest = Color(red: 0.075, green: 0.278, blue: 0.196)
    static let treeLeaf = Color(red: 0.286, green: 0.514, blue: 0.333)
    static let treeWater = Color(red: 0.122, green: 0.557, blue: 0.663)
    static let treeWarning = Color(red: 0.745, green: 0.235, blue: 0.176)
    static let treeSun = Color(red: 0.957, green: 0.725, blue: 0.314)
}

extension WateringAvailability {
    var japaneseTitle: String {
        switch self {
        case .bootGuard: "起動を確認中"
        case .ready: "水やりできます"
        case .unarmed: "給水は無効です"
        case .watering: "給水中"
        case .error: "端末エラー"
        case .unknown: "状態を確認中"
        }
    }

    var japaneseDetail: String {
        switch self {
        case .bootGuard: "安全待機が終わるまで少し待ってください"
        case .ready: "ポンプは停止しています"
        case .unarmed: "実機テスト後に端末を有効化してください"
        case .watering: "指示した時間で自動停止します"
        case .error: "端末と配線を確認してください"
        case .unknown: "アプリが未対応の端末状態です"
        }
    }

    var tint: Color {
        switch self {
        case .ready: .treeLeaf
        case .watering: .treeWater
        case .unarmed: .orange
        case .bootGuard, .unknown: .orange
        case .error: .treeWarning
        }
    }
}

struct TreeGlassBackdrop: View {
    var body: some View {
        GeometryReader { proxy in
            ZStack {
                LinearGradient(
                    colors: [
                        Color.treeCanvas,
                        Color.white,
                        Color.treeWater.opacity(0.16),
                        Color.treeLeaf.opacity(0.18),
                    ],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )

                Circle()
                    .fill(Color.treeWater.opacity(0.22))
                    .frame(width: proxy.size.width * 0.92)
                    .blur(radius: 8)
                    .offset(x: proxy.size.width * 0.50, y: -proxy.size.width * 0.34)

                Circle()
                    .fill(Color.treeSun.opacity(0.13))
                    .frame(width: proxy.size.width * 0.56)
                    .blur(radius: 18)
                    .offset(x: -proxy.size.width * 0.36, y: proxy.size.height * 0.20)

                Image(systemName: "drop.fill")
                    .font(.system(size: proxy.size.width * 0.34, weight: .bold))
                    .foregroundStyle(Color.treeWater.opacity(0.14))
                    .rotationEffect(.degrees(12))
                    .offset(x: proxy.size.width * 0.34, y: -proxy.size.height * 0.13)

                Image(systemName: "leaf.fill")
                    .font(.system(size: proxy.size.width * 0.30, weight: .bold))
                    .foregroundStyle(Color.treeLeaf.opacity(0.13))
                    .rotationEffect(.degrees(-28))
                    .offset(x: -proxy.size.width * 0.38, y: proxy.size.height * 0.12)

                Ellipse()
                    .fill(Color.treeLeaf.opacity(0.18))
                    .frame(width: proxy.size.width * 0.94, height: proxy.size.width * 0.58)
                    .rotationEffect(.degrees(24))
                    .blur(radius: 10)
                    .offset(x: -proxy.size.width * 0.40, y: proxy.size.height * 0.72)
            }
        }
        .ignoresSafeArea()
        .accessibilityHidden(true)
    }
}

struct TreeCardModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(20)
            .background(Color.white.opacity(0.72))
            .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 28, style: .continuous)
                    .stroke(Color.white.opacity(0.86), lineWidth: 1)
            }
            .shadow(color: Color.treeInk.opacity(0.06), radius: 20, y: 10)
    }
}

extension View {
    func treeCard() -> some View {
        modifier(TreeCardModifier())
    }
}

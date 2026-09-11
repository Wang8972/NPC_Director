using System;
using TMPro;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.UI;

namespace LastLight
{
    internal static class UiFactory
    {
        public static readonly Color Ink = new Color(.035f, .065f, .09f, .97f);
        public static readonly Color PanelColor = new Color(.055f, .085f, .11f, .96f);
        public static readonly Color CardColor = new Color(.09f, .135f, .16f, .97f);
        public static readonly Color Amber = new Color(.94f, .66f, .31f, 1);
        public static readonly Color TextColor = new Color(.92f, .92f, .88f, 1);
        public static readonly Color Muted = new Color(.59f, .67f, .7f, 1);
        public static readonly Color Blue = new Color(.4f, .68f, .77f, 1);
        public static readonly Color Danger = new Color(.94f, .46f, .34f, 1);
        public static TMP_FontAsset Font;
        static Sprite rounded;

        public static RectTransform Rect(string name, Transform parent)
        {
            var go = new GameObject(name, typeof(RectTransform));
            go.transform.SetParent(parent, false);
            return (RectTransform)go.transform;
        }
        public static void Fill(RectTransform rect, float left = 0, float right = 0, float top = 0, float bottom = 0)
        {
            rect.anchorMin = Vector2.zero; rect.anchorMax = Vector2.one;
            rect.offsetMin = new Vector2(left, bottom); rect.offsetMax = new Vector2(-right, -top);
        }
        public static void Place(RectTransform rect, Vector2 anchor, Vector2 pivot, float x, float y, float width, float height)
        {
            rect.anchorMin = rect.anchorMax = anchor; rect.pivot = pivot;
            rect.anchoredPosition = new Vector2(x, y); rect.sizeDelta = new Vector2(width, height);
        }
        public static Image Panel(string name, Transform parent, Color color, bool raycast = true, bool round = true)
        {
            var rect = Rect(name, parent);
            var image = rect.gameObject.AddComponent<Image>(); image.color = color; image.raycastTarget = raycast;
            if (round) { image.sprite = Rounded(); image.type = Image.Type.Sliced; }
            return image;
        }
        public static TextMeshProUGUI Text(string name, Transform parent, string value, float size = 26, Color? color = null, FontStyles style = FontStyles.Normal)
        {
            var rect = Rect(name, parent);
            var text = rect.gameObject.AddComponent<TextMeshProUGUI>(); text.font = Font;
            text.text = value ?? ""; text.fontSize = size; text.color = color ?? TextColor;
            text.fontStyle = style; text.raycastTarget = false;
            text.enableWordWrapping = true;
            text.overflowMode = TextOverflowModes.Overflow;
            text.richText = false; text.lineSpacing = 8; text.margin = Vector4.zero;
            return text;
        }
        public static TextMeshProUGUI FlowText(Transform parent, string value, float size = 25, Color? color = null, float minHeight = -1)
        {
            var text = Text("Text", parent, value, size, color);
            var fitter = text.gameObject.AddComponent<ContentSizeFitter>(); fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
            if (minHeight > 0) text.gameObject.AddComponent<LayoutElement>().minHeight = minHeight;
            return text;
        }
        public static Button Button(string name, Transform parent, string label, UnityAction click, bool primary = false, float height = 50)
        {
            var image = Panel(name, parent, primary ? Amber : CardColor);
            var button = image.gameObject.AddComponent<Button>();
            button.targetGraphic = image;
            var colors = button.colors;
            colors.normalColor = Color.white; colors.highlightedColor = new Color(1.13f, 1.13f, 1.1f, 1);
            colors.pressedColor = new Color(.73f, .79f, .8f, 1); colors.selectedColor = colors.highlightedColor;
            colors.disabledColor = new Color(.6f, .6f, .6f, .55f); button.colors = colors;
            if (click != null) button.onClick.AddListener(click);
            var layout = image.gameObject.AddComponent<LayoutElement>(); layout.preferredHeight = height; layout.minHeight = height;
            var text = Text("Label", image.transform, label, 23, primary ? Ink : TextColor, primary ? FontStyles.Bold : FontStyles.Normal);
            Fill(text.rectTransform, 13, 13, 6, 6); text.alignment = TextAlignmentOptions.Center;
            return button;
        }
        public static void SetLabel(Button button, string label)
        {
            var text = button.GetComponentInChildren<TextMeshProUGUI>(); if (text != null) text.text = label;
        }
        public static RectTransform Column(string name, Transform parent, float spacing = 12, int padding = 0)
        {
            var rect = Rect(name, parent); var layout = rect.gameObject.AddComponent<VerticalLayoutGroup>();
            layout.spacing = spacing; layout.padding = new RectOffset(padding, padding, padding, padding);
            layout.childControlHeight = true; layout.childControlWidth = true;
            layout.childForceExpandWidth = true; layout.childForceExpandHeight = false;
            return rect;
        }
        public static RectTransform Row(string name, Transform parent, float spacing = 10, float height = 50)
        {
            var rect = Rect(name, parent); var layout = rect.gameObject.AddComponent<HorizontalLayoutGroup>();
            layout.spacing = spacing; layout.childControlHeight = true; layout.childControlWidth = true;
            layout.childForceExpandWidth = true; layout.childForceExpandHeight = true;
            var le = rect.gameObject.AddComponent<LayoutElement>(); le.preferredHeight = height; le.minHeight = height;
            return rect;
        }
        public static ScrollRect Scroll(string name, Transform parent, out RectTransform content, float spacing = 12, int padding = 4)
        {
            var root = Rect(name, parent); var scroll = root.gameObject.AddComponent<ScrollRect>();
            var viewport = Panel("Viewport", root, Color.clear, true, false); Fill(viewport.rectTransform);
            viewport.gameObject.AddComponent<RectMask2D>();
            content = Column("Content", viewport.transform, spacing, padding);
            content.anchorMin = new Vector2(0, 1); content.anchorMax = Vector2.one; content.pivot = new Vector2(.5f, 1);
            content.anchoredPosition = Vector2.zero; content.sizeDelta = Vector2.zero;
            var size = content.gameObject.AddComponent<ContentSizeFitter>(); size.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
            scroll.viewport = viewport.rectTransform; scroll.content = content; scroll.horizontal = false;
            scroll.movementType = ScrollRect.MovementType.Clamped; scroll.scrollSensitivity = 36;
            return scroll;
        }
        public static TMP_InputField Input(string name, Transform parent, string placeholder, float height = 55, bool multi = false)
        {
            var image = Panel(name, parent, new Color(.025f, .048f, .068f, 1));
            var input = image.gameObject.AddComponent<TMP_InputField>(); input.targetGraphic = image;
            var viewport = Rect("TextArea", image.transform); Fill(viewport, 15, 15, 8, 8); viewport.gameObject.AddComponent<RectMask2D>();
            var text = Text("Value", viewport, "", 25); Fill(text.rectTransform); text.alignment = TextAlignmentOptions.MidlineLeft;
            var hint = Text("Placeholder", viewport, placeholder, 24, Muted); Fill(hint.rectTransform); hint.alignment = TextAlignmentOptions.MidlineLeft;
            input.textViewport = viewport; input.textComponent = text; input.placeholder = hint;
            input.fontAsset = Font; input.characterLimit = 1600; input.caretColor = Amber; input.customCaretColor = true;
            input.selectionColor = new Color(.4f, .68f, .77f, .4f);
            input.lineType = multi ? TMP_InputField.LineType.MultiLineSubmit : TMP_InputField.LineType.SingleLine;
            var le = image.gameObject.AddComponent<LayoutElement>(); le.preferredHeight = height; le.minHeight = height;
            return input;
        }
        public static Toggle Toggle(Transform parent, string label, bool initial, UnityAction<bool> changed)
        {
            var row = Row("Toggle", parent, 12, 42); var toggle = row.gameObject.AddComponent<Toggle>();
            var box = Panel("Box", row, CardColor); var le = box.gameObject.AddComponent<LayoutElement>(); le.preferredWidth = 36; le.minWidth = 36; le.flexibleWidth = 0;
            var check = Panel("Check", box.transform, Amber); Fill(check.rectTransform, 8, 8, 8, 8);
            toggle.targetGraphic = box; toggle.graphic = check; toggle.isOn = initial;
            var text = Text("Label", row, label, 24); text.alignment = TextAlignmentOptions.MidlineLeft;
            if (changed != null) toggle.onValueChanged.AddListener(changed);
            return toggle;
        }
        public static Slider Slider(Transform parent, float value, UnityAction<float> changed)
        {
            var rect = Rect("Slider", parent); var slider = rect.gameObject.AddComponent<Slider>();
            rect.gameObject.AddComponent<LayoutElement>().preferredHeight = 38;
            var bg = Panel("Track", rect, CardColor); Fill(bg.rectTransform, 0, 0, 14, 14);
            var fillArea = Rect("FillArea", rect); Fill(fillArea, 9, 9, 14, 14);
            var fill = Panel("Fill", fillArea, Amber); Fill(fill.rectTransform); slider.fillRect = fill.rectTransform;
            var handleArea = Rect("HandleArea", rect); Fill(handleArea, 10, 10);
            var handle = Panel("Handle", handleArea, TextColor);
            handle.rectTransform.sizeDelta = new Vector2(20, 30); slider.handleRect = handle.rectTransform; slider.targetGraphic = handle;
            slider.minValue = 0; slider.maxValue = 1; slider.value = value; slider.onValueChanged.AddListener(changed);
            return slider;
        }
        public static void Clear(Transform parent)
        {
            for (int i = parent.childCount - 1; i >= 0; i--) { var child = parent.GetChild(i).gameObject; child.SetActive(false); UnityEngine.Object.Destroy(child); }
        }
        public static Color ActorColor(string id)
        {
            switch (id) { case "lin": return Blue; case "zhou": return new Color(.94f,.65f,.39f); case "chen": return new Color(.61f,.78f,.61f); case "xu": return new Color(.77f,.66f,.88f); default: return TextColor; }
        }
        static Sprite Rounded()
        {
            if (rounded != null) return rounded;
            const int size = 32; const float radius = 8;
            var texture = new Texture2D(size, size, TextureFormat.RGBA32, false) { name = "LastLight UI", filterMode = FilterMode.Bilinear };
            var pixels = new Color[size * size];
            for (int y = 0; y < size; y++) for (int x = 0; x < size; x++)
            {
                var dx = Mathf.Max(radius - x - .5f, x + .5f - (size - radius));
                var dy = Mathf.Max(radius - y - .5f, y + .5f - (size - radius));
                var distance = new Vector2(Mathf.Max(0, dx), Mathf.Max(0, dy)).magnitude;
                pixels[y * size + x] = new Color(1, 1, 1, Mathf.Clamp01(radius - distance + .5f));
            }
            texture.SetPixels(pixels); texture.Apply();
            rounded = Sprite.Create(texture, new Rect(0, 0, size, size), new Vector2(.5f, .5f), 100, 0, SpriteMeshType.FullRect, new Vector4(9, 9, 9, 9));
            return rounded;
        }
    }
}

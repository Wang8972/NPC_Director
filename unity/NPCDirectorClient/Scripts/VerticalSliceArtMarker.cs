using UnityEngine;

namespace NPCDirector
{
    public enum VerticalSliceArtKind
    {
        Architecture,
        Prop,
        Character,
        StateIndicator,
        Lighting
    }

    public sealed class VerticalSliceArtMarker : MonoBehaviour
    {
        [SerializeField] private string assetId;
        [SerializeField] private VerticalSliceArtKind kind;

        public string AssetId => assetId;
        public VerticalSliceArtKind Kind => kind;

        public void Configure(string id, VerticalSliceArtKind artKind)
        {
            assetId = id;
            kind = artKind;
        }
    }
}

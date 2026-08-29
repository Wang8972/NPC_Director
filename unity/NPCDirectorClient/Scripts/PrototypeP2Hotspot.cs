using UnityEngine;

namespace NPCDirector
{
    public sealed class PrototypeP2Hotspot : MonoBehaviour
    {
        [SerializeField] private PrototypeP2GameController controller;
        [SerializeField] private string objectId;

        public void Configure(PrototypeP2GameController gameController, string configuredObjectId)
        {
            controller = gameController;
            objectId = configuredObjectId;
        }

        private void OnMouseDown()
        {
            controller?.Observe(objectId);
        }
    }
}

using UnityEngine;

namespace NPCDirector
{
    public sealed class PrototypeHotspot : MonoBehaviour
    {
        [SerializeField] private PrototypeGameFlowController controller;
        [SerializeField] private string objectId;
        private Vector3 initialScale;

        public string ObjectId => objectId;

        public void Configure(PrototypeGameFlowController flowController, string canonicalObjectId)
        {
            controller = flowController;
            objectId = canonicalObjectId;
        }

        private void Awake()
        {
            initialScale = transform.localScale;
        }

        private void OnMouseEnter()
        {
            transform.localScale = initialScale * 1.08f;
        }

        private void OnMouseExit()
        {
            transform.localScale = initialScale;
        }

        private void OnMouseDown()
        {
            if (controller == null)
            {
                Debug.LogError($"[P1_HOTSPOT] missing controller object_id={objectId}");
                return;
            }
            controller.HandleHotspot(objectId);
        }
    }
}

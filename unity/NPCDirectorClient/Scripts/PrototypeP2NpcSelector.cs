using UnityEngine;

namespace NPCDirector
{
    public sealed class PrototypeP2NpcSelector : MonoBehaviour
    {
        [SerializeField] private PrototypeP2GameController controller;
        [SerializeField] private string npcId;

        public void Configure(PrototypeP2GameController gameController, string configuredNpcId)
        {
            controller = gameController;
            npcId = configuredNpcId;
        }

        private void OnMouseDown()
        {
            controller?.SelectNpc(npcId);
        }
    }
}

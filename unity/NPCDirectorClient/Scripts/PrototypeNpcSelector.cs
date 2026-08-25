using UnityEngine;

namespace NPCDirector
{
    public sealed class PrototypeNpcSelector : MonoBehaviour
    {
        [SerializeField] private PrototypeGameFlowController controller;
        [SerializeField] private string npcId;

        public string NpcId => npcId;

        public void Configure(PrototypeGameFlowController flowController, string canonicalNpcId)
        {
            controller = flowController;
            npcId = canonicalNpcId;
        }

        private void OnMouseDown()
        {
            if (controller == null)
            {
                Debug.LogError($"[P1_NPC_SELECT] missing controller npc_id={npcId}");
                return;
            }
            controller.SelectNpc(npcId);
        }
    }
}

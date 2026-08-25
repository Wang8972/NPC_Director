using UnityEngine;

namespace NPCDirector
{
    public sealed class PrototypeUiAction : MonoBehaviour
    {
        [SerializeField] private PrototypeGameFlowController controller;
        [SerializeField] private string command;

        public void Configure(PrototypeGameFlowController flowController, string actionCommand)
        {
            controller = flowController;
            command = actionCommand;
        }

        public void InvokeAction()
        {
            if (controller == null)
            {
                Debug.LogError($"[P1_UI] missing controller command={command}");
                return;
            }
            controller.ExecuteUiCommand(command);
        }
    }
}

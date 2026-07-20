using UnityEngine;

namespace NPCDirector
{
    public sealed class GazeController : MonoBehaviour
    {
        [SerializeField] private Transform head;
        [SerializeField] private Transform playerHead;
        [SerializeField] private float turnSpeed = 6f;
        private Transform currentTarget;

        public void Apply(GazeDirective gaze)
        {
            currentTarget = gaze != null && gaze.target == "player_head" ? playerHead : null;
        }

        private void LateUpdate()
        {
            if (head == null || currentTarget == null)
            {
                return;
            }
            Vector3 direction = currentTarget.position - head.position;
            if (direction.sqrMagnitude < 0.0001f)
            {
                return;
            }
            Quaternion target = Quaternion.LookRotation(direction.normalized, Vector3.up);
            head.rotation = Quaternion.Slerp(head.rotation, target, turnSpeed * Time.deltaTime);
        }
    }
}
